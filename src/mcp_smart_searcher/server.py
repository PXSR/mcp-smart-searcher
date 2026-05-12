"""
MCP Smart Searcher - A smart MCP server for multi-engine web search with AI-powered results
"""

import asyncio
import logging
import os
import re
import time
import urllib.parse
from typing import Any

import httpx
from bs4 import BeautifulSoup
from mcp.server.fastmcp import FastMCP

# Optional dependencies for advanced content extraction
try:
    from markdownify import markdownify as _md_converter
    HAS_MARKDOWNIFY = True
except ImportError:
    HAS_MARKDOWNIFY = False

try:
    from readability import Document as ReadabilityDocument
    HAS_READABILITY = True
except ImportError:
    HAS_READABILITY = False

# Configure logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("mcp_smart_searcher")

# Create FastMCP server instance (required for mcp dev/inspector)
mcp = FastMCP("smart-searcher")

# Configuration from environment variables
DEFAULT_SEARCH_ENGINES = [
    e.strip()
    for e in os.getenv("DEFAULT_SEARCH_ENGINES", "duckduckgo,baidu,startpage,tavily,brave").split(",")
    if e.strip()
]
ALLOWED_SEARCH_ENGINES = os.getenv("ALLOWED_SEARCH_ENGINES", "").split(",") if os.getenv("ALLOWED_SEARCH_ENGINES") else None
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
USE_PROXY = os.getenv("USE_PROXY", "true").lower() == "true"
PROXY_URL = os.getenv("PROXY_URL", "http://127.0.0.1:10809")
# Comma-separated list of engines that should use proxy. Empty means ALL engines use proxy (legacy behavior).
PROXY_ENGINES = [e.strip() for e in os.getenv("PROXY_ENGINES", "").split(",") if e.strip()] if os.getenv("PROXY_ENGINES") else None

# Rate limiting: max concurrent search engine requests
MAX_CONCURRENT_SEARCH = int(os.getenv("MAX_CONCURRENT_SEARCH", "5"))
_search_semaphore = asyncio.Semaphore(MAX_CONCURRENT_SEARCH)


# User agent for requests
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Supported search engines
ALL_ENGINES = ["duckduckgo", "baidu", "juejin", "github", "github_code", "tavily", "brave", "startpage"]


# Engines that should NOT use proxy by default (domestic engines)
NO_PROXY_ENGINES = {"baidu", "juejin"}


def get_proxy_config(engine: str = None) -> dict:
    """Get proxy configuration for a specific engine.

    Domestic engines (baidu, juejin) skip proxy by default.
    All other engines use proxy when USE_PROXY is true.

    Args:
        engine: The search engine name. If None, returns global proxy config.

    Returns:
        Dict with 'proxy' key if proxy is enabled for this engine.
    """
    if not USE_PROXY:
        return {}
    # If PROXY_ENGINES is explicitly set, only those engines use proxy
    if PROXY_ENGINES is not None:
        if engine in PROXY_ENGINES:
            return {"proxy": PROXY_URL}
        return {}
    # Default: skip proxy for domestic engines
    if engine in NO_PROXY_ENGINES:
        return {}
    return {"proxy": PROXY_URL}


def is_engine_allowed(engine: str) -> bool:
    """Check if a search engine is allowed."""
    if ALLOWED_SEARCH_ENGINES is None or not ALLOWED_SEARCH_ENGINES[0]:
        return engine in ALL_ENGINES
    return engine in ALLOWED_SEARCH_ENGINES


async def fetch_url(
    client: httpx.AsyncClient,
    url: str,
    headers: dict = None,
    max_retries: int = 2,
    timeout: float = 30.0,
) -> str:
    """Fetch URL content with error handling and retry logic.

    Retries on timeout and connection errors. Does NOT retry on HTTP 4xx errors
    (client errors), only on 5xx server errors.

    Args:
        client: httpx AsyncClient instance
        url: URL to fetch
        headers: Optional request headers
        max_retries: Number of retry attempts (default 2)
        timeout: Request timeout in seconds (default 30)

    Returns:
        Response text or error message.
    """
    RETRYABLE_EXCEPTIONS = (
        httpx.TimeoutException,
        httpx.ConnectError,
        httpx.ReadError,
        httpx.WriteError,
        httpx.PoolTimeout,
    )
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            start = time.monotonic()
            response = await client.get(
                url, headers=headers or {}, timeout=timeout, follow_redirects=True
            )
            elapsed = time.monotonic() - start
            logger.debug("Fetched %s -> %d (%.2fs)", url, response.status_code, elapsed)
            response.raise_for_status()
            return response.text
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if 500 <= status < 600:
                last_error = f"Server error {status} fetching {url} (attempt {attempt + 1}/{max_retries + 1})"
                logger.warning(last_error)
                continue
            return f"Error fetching {url}: HTTP {status} {e.response.reason_phrase}"
        except RETRYABLE_EXCEPTIONS as e:
            last_error = f"{type(e).__name__} fetching {url} (attempt {attempt + 1}/{max_retries + 1})"
            logger.warning(last_error)
        except Exception as e:
            return f"Error fetching {url}: {type(e).__name__}: {str(e)}"

    return last_error or f"Error fetching {url}: unknown error"


async def search_duckduckgo(query: str, limit: int) -> list[dict]:
    """Search using DuckDuckGo."""
    async with _search_semaphore:
        results = []
        logger.info("DuckDuckGo search: query=%r limit=%d", query, limit)
        async with httpx.AsyncClient(**get_proxy_config("duckduckgo")) as client:
            try:
                url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
                headers = {"User-Agent": USER_AGENT}
                html = await fetch_url(client, url, headers)
                soup = BeautifulSoup(html, "lxml")

                items = soup.select(".result")[:limit]
                if not items:
                    items = soup.select("[class*='result']")[:limit]
                if not items:
                    logger.warning("DuckDuckGo returned no results for query=%r (CSS selectors matched nothing)", query)

                for item in items:
                    title_elem = item.select_one(".result__a")
                    snippet_elem = item.select_one(".result__snippet")
                    if title_elem:
                        results.append({
                            "title": title_elem.get_text(strip=True),
                            "url": title_elem.get("href", ""),
                            "snippet": snippet_elem.get_text(strip=True) if snippet_elem else "",
                            "engine": "duckduckgo"
                        })
                logger.info("DuckDuckGo returned %d results", len(results))
            except Exception as e:
                logger.error("DuckDuckGo search failed: %s", str(e), exc_info=True)
                results.append({"error": f"DuckDuckGo search failed: {str(e)}", "engine": "duckduckgo"})
        return results


async def search_baidu(query: str, limit: int) -> list[dict]:
    """Search using Baidu."""
    async with _search_semaphore:
        results = []
        logger.info("Baidu search: query=%r limit=%d", query, limit)
        async with httpx.AsyncClient(**get_proxy_config("baidu")) as client:
            try:
                url = f"https://www.baidu.com/s?wd={urllib.parse.quote(query)}&rn={limit}"
                headers = {"User-Agent": USER_AGENT}
                html = await fetch_url(client, url, headers)
                soup = BeautifulSoup(html, "lxml")

                items = soup.select(".result")[:limit]
                if not items:
                    items = soup.select("[class*='result']")[:limit]
                if not items:
                    logger.warning("Baidu returned no results for query=%r (CSS selectors matched nothing)", query)

                for item in items:
                    title_elem = item.select_one("h3 a")
                    snippet_elem = item.select_one(".c-abstract")
                    if not snippet_elem:
                        snippet_elem = item.select_one("[class*='abstract']")
                    if title_elem:
                        results.append({
                            "title": title_elem.get_text(strip=True),
                            "url": title_elem.get("href", ""),
                            "snippet": snippet_elem.get_text(strip=True) if snippet_elem else "",
                            "engine": "baidu"
                        })
                logger.info("Baidu returned %d results", len(results))
            except Exception as e:
                logger.error("Baidu search failed: %s", str(e), exc_info=True)
                results.append({"error": f"Baidu search failed: {str(e)}", "engine": "baidu"})
        return results


async def search_juejin(query: str, limit: int) -> list[dict]:
    """Search using Juejin."""
    async with _search_semaphore:
        results = []
        logger.info("Juejin search: query=%r limit=%d", query, limit)
        async with httpx.AsyncClient(**get_proxy_config("juejin")) as client:
            try:
                url = "https://api.juejin.cn/content_api/v1/search"
                headers = {"Content-Type": "application/json"}
                data = {
                    "id_type": 2,
                    "limit": limit,
                    "sort_type": 200,
                    "keyword": query,
                    "search_type": 0
                }

                response = await client.post(url, headers=headers, json=data, timeout=30.0)
                response.raise_for_status()
                result = response.json()

                for item in result.get("data", [])[:limit]:
                    results.append({
                        "title": item.get("article", {}).get("title", ""),
                        "url": f"https://juejin.cn/post/{item.get('article', {}).get('article_id', '')}",
                        "snippet": item.get("article", {}).get("brief_content", ""),
                        "engine": "juejin"
                    })
                logger.info("Juejin returned %d results", len(results))
            except Exception as e:
                logger.error("Juejin search failed: %s", str(e), exc_info=True)
                results.append({"error": f"Juejin search failed: {str(e)}", "engine": "juejin"})
        return results


async def search_github(query: str, limit: int) -> list[dict]:
    """Search GitHub repositories."""
    async with _search_semaphore:
        results = []
        logger.info("GitHub search: query=%r limit=%d", query, limit)
        async with httpx.AsyncClient(**get_proxy_config("github")) as client:
            try:
                url = f"https://api.github.com/search/repositories?q={urllib.parse.quote(query)}&per_page={limit}"
                headers = {"Accept": "application/vnd.github.v3+json"}
                if GITHUB_TOKEN:
                    headers["Authorization"] = f"token {GITHUB_TOKEN}"

                response = await client.get(url, headers=headers, timeout=30.0)
                response.raise_for_status()
                data = response.json()

                for item in data.get("items", [])[:limit]:
                    results.append({
                        "title": item.get("full_name", ""),
                        "url": item.get("html_url", ""),
                        "snippet": item.get("description", "") or "",
                        "engine": "github"
                    })
                logger.info("GitHub returned %d results", len(results))
            except Exception as e:
                logger.error("GitHub search failed: %s", str(e), exc_info=True)
                results.append({"error": f"GitHub search failed: {str(e)}", "engine": "github"})
        return results


async def search_github_code(query: str, limit: int) -> list[dict]:
    """Search GitHub code."""
    async with _search_semaphore:
        results = []
        logger.info("GitHub code search: query=%r limit=%d", query, limit)
        async with httpx.AsyncClient(**get_proxy_config("github_code")) as client:
            try:
                url = f"https://api.github.com/search/code?q={urllib.parse.quote(query)}&per_page={limit}"
                headers = {"Accept": "application/vnd.github.v3+json"}
                if GITHUB_TOKEN:
                    headers["Authorization"] = f"token {GITHUB_TOKEN}"

                response = await client.get(url, headers=headers, timeout=30.0)
                response.raise_for_status()
                data = response.json()

                for item in data.get("items", [])[:limit]:
                    results.append({
                        "title": item.get("name", ""),
                        "url": item.get("html_url", ""),
                        "snippet": f"In repository: {item.get('repository', {}).get('full_name', '')}",
                        "engine": "github_code"
                    })
                logger.info("GitHub code returned %d results", len(results))
            except Exception as e:
                logger.error("GitHub code search failed: %s", str(e), exc_info=True)
                results.append({"error": f"GitHub code search failed: {str(e)}", "engine": "github_code"})
        return results


async def search_tavily(query: str, limit: int) -> list[dict]:
    """Search using Tavily AI Search API."""
    if not TAVILY_API_KEY:
        logger.warning("Tavily search skipped: TAVILY_API_KEY not configured")
        return [{"error": "Tavily API key not configured", "engine": "tavily"}]

    async with _search_semaphore:
        results = []
        logger.info("Tavily search: query=%r limit=%d", query, limit)
        async with httpx.AsyncClient(**get_proxy_config("tavily")) as client:
            try:
                url = "https://api.tavily.com/search"
                headers = {"Content-Type": "application/json"}
                data = {
                    "api_key": TAVILY_API_KEY,
                    "query": query,
                    "search_depth": "advanced",
                    "max_results": limit,
                    "include_answer": True,
                }

                response = await client.post(url, headers=headers, json=data, timeout=30.0)
                response.raise_for_status()
                result = response.json()

                # Include AI-generated answer as first result
                if result.get("answer"):
                    results.append({
                        "title": "[Tavily AI Answer]",
                        "url": "",
                        "snippet": result["answer"],
                        "engine": "tavily",
                        "score": 1.0,
                    })

                for item in result.get("results", [])[:limit]:
                    results.append({
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "snippet": item.get("content", ""),
                        "engine": "tavily",
                        "score": item.get("score"),
                    })
                logger.info("Tavily returned %d results", len(results))
            except Exception as e:
                logger.error("Tavily search failed: %s", str(e), exc_info=True)
                results.append({"error": f"Tavily search failed: {str(e)}", "engine": "tavily"})
        return results


async def search_brave(query: str, limit: int) -> list[dict]:
    """Search using Brave Search."""
    async with _search_semaphore:
        results = []
        logger.info("Brave search: query=%r limit=%d", query, limit)
        async with httpx.AsyncClient(**get_proxy_config("brave")) as client:
            try:
                url = f"https://search.brave.com/search?q={urllib.parse.quote(query)}"
                headers = {
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Encoding": "gzip, deflate",
                    "Accept-Language": "en-US,en;q=0.9",
                }
                html = await fetch_url(client, url, headers)
                if html.startswith("Error"):
                    logger.warning("Brave fetch failed for query=%r: %s", query, html)
                    results.append({"error": html, "engine": "brave"})
                    return results

                soup = BeautifulSoup(html, "lxml")

                cards = soup.select('[data-type="web"]')[:limit]
                if not cards:
                    logger.warning("Brave returned no results for query=%r (CSS selectors matched nothing)", query)

                for card in cards:
                    title_el = card.select_one(".title") or card.select_one(".heading-medium")
                    url_el = card.select_one("a[href]")
                    snippet_el = card.select_one("[class*='snippet']") or card.select_one(".description")
                    if title_el:
                        href = url_el.get("href", "") if url_el else ""
                        if not href.startswith("http"):
                            href = ""
                        results.append({
                            "title": title_el.get_text(strip=True),
                            "url": href,
                            "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
                            "engine": "brave",
                        })
                logger.info("Brave returned %d results", len(results))
            except Exception as e:
                logger.error("Brave search failed: %s", str(e), exc_info=True)
                results.append({"error": f"Brave search failed: {str(e)}", "engine": "brave"})
        return results


async def search_startpage(query: str, limit: int) -> list[dict]:
    """Search using Startpage (Google proxy)."""
    async with _search_semaphore:
        results = []
        logger.info("Startpage search: query=%r limit=%d", query, limit)
        async with httpx.AsyncClient(**get_proxy_config("startpage")) as client:
            try:
                url = f"https://www.startpage.com/sp/search?query={urllib.parse.quote(query)}"
                headers = {
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Encoding": "gzip, deflate",
                    "Accept-Language": "en-US,en;q=0.9",
                }
                html = await fetch_url(client, url, headers)
                if html.startswith("Error"):
                    logger.warning("Startpage fetch failed for query=%r: %s", query, html)
                    results.append({"error": html, "engine": "startpage"})
                    return results

                soup = BeautifulSoup(html, "lxml")

                cards = soup.select(".result")[:limit]
                if not cards:
                    logger.warning("Startpage returned no results for query=%r (CSS selectors matched nothing)", query)

                for card in cards:
                    title_el = card.select_one("a.result-title") or card.select_one("h3 a")
                    url_el = card.select_one("a[href^='http']")
                    snippet_el = card.select_one(".description") or card.select_one("[class*='description']")
                    if title_el:
                        href = url_el.get("href", "") if url_el else ""
                        results.append({
                            "title": title_el.get_text(strip=True),
                            "url": href,
                            "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
                            "engine": "startpage",
                        })
                logger.info("Startpage returned %d results", len(results))
            except Exception as e:
                logger.error("Startpage search failed: %s", str(e), exc_info=True)
                results.append({"error": f"Startpage search failed: {str(e)}", "engine": "startpage"})
        return results


# Search engine mapping
SEARCH_ENGINES = {
    "duckduckgo": search_duckduckgo,
    "baidu": search_baidu,
    "juejin": search_juejin,
    "github": search_github,
    "github_code": search_github_code,
    "tavily": search_tavily,
    "brave": search_brave,
    "startpage": search_startpage,
}


@mcp.tool()
async def web_search(query: str, engines: list[str] = None, limit: int = 10) -> str:
    """
    Search the web using one or more search engines simultaneously.

    Default engines: duckduckgo, baidu, startpage, tavily, brave.
    Configure via DEFAULT_SEARCH_ENGINES env var (comma-separated).

    Args:
        query: Search query string (non-empty)
        engines: Search engines to use (duckduckgo, baidu, juejin, github, github_code, tavily, brave, startpage).
                 When omitted, uses all DEFAULT_SEARCH_ENGINES.
        limit: Maximum number of results per engine (1-50, default 10)

    Returns:
        Formatted search results from all specified engines
    """
    # Input validation
    if not query or not query.strip():
        return "Error: query must be a non-empty string"
    query = query.strip()

    if engines is None:
        engines = DEFAULT_SEARCH_ENGINES

    limit = min(max(limit, 1), 50)

    # Filter allowed engines
    engines = [e for e in engines if is_engine_allowed(e)]
    if not engines:
        engines = [e for e in DEFAULT_SEARCH_ENGINES if is_engine_allowed(e)]

    if not engines:
        return "No allowed search engines configured"

    # Filter to only implemented engines
    active_engines = [e for e in engines if e in SEARCH_ENGINES]
    skipped = set(engines) - set(active_engines)
    if skipped:
        logger.warning("Skipping unimplemented engines: %s", skipped)

    logger.info("web_search: query=%r engines=%s limit=%d", query, active_engines, limit)

    # Execute searches in parallel (each engine creates its own client with proxy config)
    tasks = [SEARCH_ENGINES[engine](query, limit) for engine in active_engines]
    all_results = await asyncio.gather(*tasks)

    # Format results
    output = []
    total_results = 0
    for engine_results in all_results:
        for result in engine_results:
            if "error" in result:
                output.append(f"[{result['engine']}] Error: {result['error']}")
            else:
                output.append(f"[{result['engine']}] {result['title']}\n{result['url']}\n{result['snippet']}\n")
                total_results += 1

    logger.info("web_search: returned %d total results", total_results)
    return "\n".join(output) if output else "No results found"


def _filter_content_by_prompt(text: str, prompt: str, max_chars: int) -> str:
    """Filter extracted text based on prompt guidance.

    Uses keyword matching to score and rank paragraphs by relevance
    to the prompt, returning the most relevant content first.
    """
    prompt_lower = prompt.lower()
    prompt_keywords = set(re.findall(r"\w+", prompt_lower))

    if not prompt_keywords:
        return text[:max_chars]

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        return text[:max_chars]

    # Score each paragraph by keyword overlap
    scored = []
    for para in paragraphs:
        para_words = set(re.findall(r"\w+", para.lower()))
        score = len(prompt_keywords & para_words) / max(len(prompt_keywords), 1)
        scored.append((score, para))

    # Sort by relevance score descending, keep original order for ties
    scored.sort(key=lambda x: x[0], reverse=True)

    # Build output from highest-scoring paragraphs until max_chars
    selected = []
    current_len = 0
    for score, para in scored:
        if current_len + len(para) + 2 > max_chars:
            break
        selected.append(para)
        current_len += len(para) + 2

    if not selected:
        return text[:max_chars]

    return "\n\n".join(selected)


# ─── Content extraction helpers ───

def _clean_html(soup: BeautifulSoup) -> BeautifulSoup:
    """Remove noise from HTML before conversion.

    Removes scripts, styles, navs, ads, hidden elements, and inline styles.
    Returns a new cleaned BeautifulSoup object.
    """
    soup = BeautifulSoup(str(soup), "lxml")

    # Remove noisy tags
    for element in soup(
        ["script", "style", "nav", "header", "footer", "aside", "iframe", "noscript", "svg"]
    ):
        element.decompose()

    # Remove ad/sidebar containers by class/id patterns
    for element in soup.find_all(class_=re.compile(r"(ad-|banner|sidebar|promo|sponsored)", re.I)):
        element.decompose()

    # Remove elements that are visually hidden (waste tokens with no value)
    for element in soup.find_all():
        style = element.get("style", "")
        if "display:none" in style or "visibility:hidden" in style:
            element.decompose()
            continue
        if element.get("aria-hidden") == "true":
            element.decompose()
            continue
        # Strip inline style attributes — they add noise without semantic value
        if element.get("style"):
            del element.attrs["style"]

    # Remove empty block-level containers that serve no structural purpose
    EMPTY_TAGS = {"div", "span", "section", "article", "p", "li"}
    for _ in range(3):  # Multiple passes for nested empties
        removed = False
        for element in soup.find_all():
            if element.name in EMPTY_TAGS:
                text = element.get_text(strip=True)
                if not text and not element.find_all(["img", "iframe", "video", "audio"]):
                    # Keep if it has meaningful attributes (id, class, role)
                    if not any(element.get(a) for a in ("id", "class", "role")):
                        element.decompose()
                        removed = True
        if not removed:
            break

    return soup


def _html_to_markdown(html: str) -> str:
    """Convert cleaned HTML to Markdown using markdownify."""
    if not HAS_MARKDOWNIFY:
        # Graceful fallback: extract plain text
        soup = BeautifulSoup(html, "lxml")
        return soup.get_text(separator="\n", strip=True)

    md = _md_converter(
        html,
        heading_style="ATX",
        bullets="-",
        strip=["script", "style", "noscript"],
    )
    # Collapse excessive blank lines
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()


def _extract_article(html: str) -> str | None:
    """Extract article body using Mozilla Readability. Returns HTML or None."""
    if not HAS_READABILITY:
        return None
    try:
        doc = ReadabilityDocument(html)
        summary = doc.summary()
        if not summary or len(summary) < 100:
            return None
        return summary
    except Exception:
        return None


def _extract_outline(soup: BeautifulSoup) -> str:
    """Generate a structural outline of the page.

    Returns headings hierarchy, semantic regions, and interactive element counts.
    Useful for AI agents to understand page layout before reading full content.
    """
    lines: list[str] = []
    lines.append("Page Outline")
    lines.append("=" * 40)

    # Title
    title_tag = soup.find("title")
    if title_tag and title_tag.get_text(strip=True):
        lines.append(f"Title: {title_tag.get_text(strip=True)}")
        lines.append("")

    # Headings hierarchy
    headings = soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])
    if headings:
        lines.append("Headings:")
        for h in headings:
            level = int(h.name[1])
            text = h.get_text(strip=True)
            if text:
                lines.append(f"{'  ' * (level - 1)}- {h.name.upper()}: {text}")
        lines.append("")

    # Semantic regions
    regions = soup.find_all(["main", "article", "section", "nav", "aside", "form"])
    if regions:
        lines.append("Regions:")
        for region in regions:
            tag = region.name
            rid = region.get("id", "")
            rcls = " ".join(region.get("class", []))[:40]
            desc = f"<{tag}>"
            if rid:
                desc += f" #{rid}"
            if rcls:
                desc += f" .{rcls}"
            # Count interactive children
            links = len(region.find_all("a", href=True))
            inputs = len(region.find_all(["input", "textarea", "select"]))
            buttons = len(region.find_all("button"))
            inter = []
            if links:
                inter.append(f"{links} link")
            if inputs:
                inter.append(f"{inputs} input")
            if buttons:
                inter.append(f"{buttons} button")
            if inter:
                desc += f" | {', '.join(inter)}"
            lines.append(f"  - {desc}")
        lines.append("")

    # Global interactive summary
    total_links = len(soup.find_all("a", href=True))
    total_inputs = len(soup.find_all(["input", "textarea", "select"]))
    total_buttons = len(soup.find_all("button"))
    total_images = len(soup.find_all("img"))
    lines.append(
        f"[Summary] {total_links} links, {total_inputs} inputs, {total_buttons} buttons, {total_images} images"
    )

    return "\n".join(lines)


@mcp.tool()
async def fetch_web_content(
    url: str,
    prompt: str = None,
    max_chars: int = 30000,
    format: str = "markdown",
) -> str:
    """
    Fetch and extract content from any public URL.

    Args:
        url: Public HTTP/HTTPS URL to fetch
        prompt: Optional hint for what to extract. When provided, the content
                is filtered to prioritize paragraphs most relevant to the
                prompt keywords. Useful for AI agents to focus on specific
                content (e.g., "extract code examples only",
                "summarize the main argument").
        max_chars: Maximum characters to return (default 30000)
        format: Output format — "markdown" (default, structured Markdown),
                "article" (reader-mode extraction as Markdown, best for blogs/docs),
                "text" (plain text, legacy behavior),
                "outline" (page structure overview only, no full content).

    Returns:
        Extracted content from the webpage in the requested format.
    """
    # Input validation
    if not url or not url.strip():
        return "Error: url must be a non-empty string"
    url = url.strip()
    if not re.match(r"^https?://", url, re.IGNORECASE):
        return f"Error: invalid URL format: {url} (must start with http:// or https://)"

    format = (format or "markdown").strip().lower()
    if format not in ("markdown", "article", "text", "outline"):
        return f"Error: invalid format: {format}. Must be one of: markdown, article, text, outline"

    logger.info("fetch_web_content: url=%r format=%r prompt=%r max_chars=%d", url, format, prompt, max_chars)

    async with httpx.AsyncClient(**get_proxy_config()) as client:
        headers = {"User-Agent": USER_AGENT}
        html = await fetch_url(client, url, headers)

        if html.startswith("Error"):
            logger.warning("fetch_web_content failed for %s: %s", url, html)
            return html

        # ── outline mode: structural overview only ──
        if format == "outline":
            soup = BeautifulSoup(html, "lxml")
            soup = _clean_html(soup)
            outline = _extract_outline(soup)
            output = f"URL: {url}\n\n{outline}"
            if len(output) > max_chars:
                output = output[:max_chars] + "...\n[Content truncated]"
            return output

        # ── article mode: readability extraction ──
        if format == "article":
            if not HAS_READABILITY:
                logger.warning("readability-lxml not installed; falling back to markdown mode for %s", url)
                format = "markdown"
            else:
                article_html = _extract_article(html)
                if article_html:
                    soup = BeautifulSoup(article_html, "lxml")
                    soup = _clean_html(soup)
                    text = _html_to_markdown(str(soup))
                else:
                    logger.warning("Readability extraction failed for %s; falling back to markdown mode", url)
                    format = "markdown"

        # ── markdown mode: full page as markdown ──
        if format == "markdown":
            soup = BeautifulSoup(html, "lxml")
            soup = _clean_html(soup)
            text = _html_to_markdown(str(soup))

        # ── text mode: legacy plain text ──
        if format == "text":
            soup = BeautifulSoup(html, "lxml")

            # Remove noisy elements (legacy behavior)
            for element in soup(
                ["script", "style", "nav", "header", "footer", "aside", "iframe", "noscript", "svg"]
            ):
                element.decompose()
            for element in soup.find_all(class_=re.compile(r"(ad-|banner|sidebar|promo|sponsored)", re.I)):
                element.decompose()

            article = (
                soup.select_one("article")
                or soup.select_one("main")
                or soup.select_one("#content")
                or soup.select_one(".content")
            )
            if article:
                for element in article(["script", "style"]):
                    element.decompose()
                text = article.get_text(separator="\n", strip=True)
            else:
                text = soup.get_text(separator="\n", strip=True)

            lines = (line.strip() for line in text.splitlines())
            text = "\n".join(line for line in lines if line)

        # Build output with header budget awareness so content filtering
        # and truncation respect the actual space available for body text.
        if prompt and prompt.strip():
            prompt = prompt.strip()
            header = f"URL: {url}\nExtraction prompt: {prompt}\n\n"
            available = max(0, max_chars - len(header))
            logger.debug("Applying prompt filter: %r", prompt)
            text = _filter_content_by_prompt(text, prompt, available)
            output = header + text
        else:
            header = f"URL: {url}\n\n"
            available = max(0, max_chars - len(header))
            text = text[:available]
            output = header + text

        if len(output) > max_chars:
            output = output[:max_chars] + "...\n[Content truncated]"

        return output
