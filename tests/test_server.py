"""Unit tests for mcp-smart-searcher server."""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio

from mcp_smart_searcher.server import (
    fetch_url,
    get_proxy_config,
    is_engine_allowed,
    search_baidu,
    search_brave,
    search_duckduckgo,
    search_github,
    search_github_code,
    search_juejin,
    search_startpage,
    search_tavily,
    web_search,
    fetch_web_content,
    _filter_content_by_prompt,
    ALL_ENGINES,
    SEARCH_ENGINES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

HTML_DUCKDUCKGO = """
<html>
<body>
<div class="result"><a class="result__a" href="https://example.com">DDG Title</a><div class="result__snippet">DDG snippet</div></div>
</body>
</html>
"""

HTML_BAIDU = """
<html>
<body>
<div class="result"><h3><a href="https://example.com">Baidu Title</a></h3><div class="c-abstract">Baidu snippet</div></div>
</body>
</html>
"""

HTML_BRAVE = """
<html>
<body>
<div data-type="web" class="snippet svelte-jmfu5f">
    <a href="https://example.com/brave-result" class="heading">
        <div class="title">Brave Search Result</div>
    </a>
    <div class="description snippet">Brave result snippet text here</div>
</div>
<div data-type="web" class="snippet svelte-jmfu5f">
    <a href="https://example.com/brave-second" class="heading">
        <div class="title">Brave Second Result</div>
    </a>
    <div class="description snippet">Second brave snippet</div>
</div>
</body>
</html>
"""

HTML_STARTPAGE = """
<html>
<body>
<div class="result css-o7i03b">
    <a class="result-title" href="https://example.com/sp-result">Startpage Result Title</a>
    <div class="description">Startpage result snippet text here</div>
</div>
<div class="result css-o7i03b">
    <a class="result-title" href="https://example.com/sp-second">Startpage Second Result</a>
    <div class="description">Second startpage snippet</div>
</div>
</body>
</html>
"""


def make_mock_client(response_text: str, status_code: int = 200, json_data: dict = None) -> AsyncMock:
    """Create a mock httpx.AsyncClient that returns the given response text."""
    mock_response = MagicMock()
    mock_response.text = response_text
    mock_response.status_code = status_code
    mock_response.raise_for_status = MagicMock()
    if json_data is not None:
        mock_response.json = MagicMock(return_value=json_data)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


# ---------------------------------------------------------------------------
# Tests: get_proxy_config
# ---------------------------------------------------------------------------

class TestGetProxyConfig:
    def test_proxy_disabled(self):
        with patch("mcp_smart_searcher.server.USE_PROXY", False):
            assert get_proxy_config("bing") == {}

    def test_proxy_enabled_all_engines(self):
        with patch("mcp_smart_searcher.server.USE_PROXY", True), \
             patch("mcp_smart_searcher.server.PROXY_ENGINES", None), \
             patch("mcp_smart_searcher.server.PROXY_URL", "http://proxy:8080"):
            assert get_proxy_config("bing") == {"proxy": "http://proxy:8080"}

    def test_proxy_specific_engines_only(self):
        with patch("mcp_smart_searcher.server.USE_PROXY", True), \
             patch("mcp_smart_searcher.server.PROXY_ENGINES", ["bing", "brave"]), \
             patch("mcp_smart_searcher.server.PROXY_URL", "http://proxy:8080"):
            assert get_proxy_config("bing") == {"proxy": "http://proxy:8080"}
            assert get_proxy_config("duckduckgo") == {}


# ---------------------------------------------------------------------------
# Tests: is_engine_allowed
# ---------------------------------------------------------------------------

class TestIsEngineAllowed:
    def test_no_allowlist_allows_all(self):
        with patch("mcp_smart_searcher.server.ALLOWED_SEARCH_ENGINES", None):
            assert is_engine_allowed("duckduckgo") is True
            assert is_engine_allowed("baidu") is True

    def test_allowlist_filters(self):
        with patch("mcp_smart_searcher.server.ALLOWED_SEARCH_ENGINES", ["duckduckgo", "baidu"]):
            assert is_engine_allowed("duckduckgo") is True
            assert is_engine_allowed("baidu") is True
            assert is_engine_allowed("github") is False

    def test_empty_allowlist_allows_all(self):
        with patch("mcp_smart_searcher.server.ALLOWED_SEARCH_ENGINES", [""]):
            assert is_engine_allowed("duckduckgo") is True


# ---------------------------------------------------------------------------
# Tests: fetch_url
# ---------------------------------------------------------------------------

class TestFetchUrl:
    @pytest.mark.asyncio
    async def test_successful_fetch(self):
        mock_client = make_mock_client("<html>hello</html>")
        result = await fetch_url(mock_client, "https://example.com")
        assert result == "<html>hello</html>"

    @pytest.mark.asyncio
    async def test_timeout_retries(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        result = await fetch_url(mock_client, "https://example.com", max_retries=1)
        assert "Timeout" in result
        assert mock_client.get.call_count == 2  # initial + 1 retry

    @pytest.mark.asyncio
    async def test_connect_error_retries(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        result = await fetch_url(mock_client, "https://example.com", max_retries=1)
        assert "ConnectError" in result
        assert mock_client.get.call_count == 2

    @pytest.mark.asyncio
    async def test_500_retries(self):
        mock_response_500 = MagicMock()
        mock_response_500.status_code = 500
        mock_response_500.reason_phrase = "Internal Server Error"
        mock_response_500.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("500", request=MagicMock(), response=mock_response_500)
        )

        mock_response_200 = MagicMock()
        mock_response_200.text = "<html>ok</html>"
        mock_response_200.status_code = 200
        mock_response_200.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[mock_response_500, mock_response_200])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        result = await fetch_url(mock_client, "https://example.com", max_retries=2)
        assert result == "<html>ok</html>"
        assert mock_client.get.call_count == 2

    @pytest.mark.asyncio
    async def test_404_no_retry(self):
        mock_response_404 = MagicMock()
        mock_response_404.status_code = 404
        mock_response_404.reason_phrase = "Not Found"
        mock_response_404.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("404", request=MagicMock(), response=mock_response_404)
        )

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response_404)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        result = await fetch_url(mock_client, "https://example.com", max_retries=2)
        assert "HTTP 404" in result
        assert mock_client.get.call_count == 1  # no retries on 4xx


# ---------------------------------------------------------------------------
# Tests: search_duckduckgo
# ---------------------------------------------------------------------------

class TestSearchDuckDuckGo:
    @pytest.mark.asyncio
    async def test_returns_results(self):
        mock_client = make_mock_client(HTML_DUCKDUCKGO)
        with patch("mcp_smart_searcher.server.httpx.AsyncClient", return_value=mock_client):
            results = await search_duckduckgo("test", 5)
        assert len(results) == 1
        assert results[0]["title"] == "DDG Title"
        assert results[0]["engine"] == "duckduckgo"


# ---------------------------------------------------------------------------
# Tests: search_baidu
# ---------------------------------------------------------------------------

class TestSearchBaidu:
    @pytest.mark.asyncio
    async def test_returns_results(self):
        mock_client = make_mock_client(HTML_BAIDU)
        with patch("mcp_smart_searcher.server.httpx.AsyncClient", return_value=mock_client):
            results = await search_baidu("test", 5)
        assert len(results) == 1
        assert results[0]["title"] == "Baidu Title"
        assert results[0]["engine"] == "baidu"


# ---------------------------------------------------------------------------
# Tests: search_juejin
# ---------------------------------------------------------------------------

class TestSearchJuejin:
    @pytest.mark.asyncio
    async def test_returns_results(self):
        json_data = {"data": [{"article": {"title": "Juejin Post", "article_id": "12345", "brief_content": "Brief"}}]}
        mock_client = make_mock_client("{}", json_data=json_data)
        with patch("mcp_smart_searcher.server.httpx.AsyncClient", return_value=mock_client):
            results = await search_juejin("test", 5)
        assert len(results) == 1
        assert results[0]["title"] == "Juejin Post"
        assert results[0]["url"] == "https://juejin.cn/post/12345"
        assert results[0]["engine"] == "juejin"


# ---------------------------------------------------------------------------
# Tests: search_github
# ---------------------------------------------------------------------------

class TestSearchGithub:
    @pytest.mark.asyncio
    async def test_returns_results(self):
        json_data = {"items": [{"full_name": "user/repo", "html_url": "https://github.com/user/repo", "description": "A repo"}]}
        mock_client = make_mock_client("{}", json_data=json_data)
        with patch("mcp_smart_searcher.server.httpx.AsyncClient", return_value=mock_client):
            results = await search_github("test", 5)
        assert len(results) == 1
        assert results[0]["title"] == "user/repo"
        assert results[0]["engine"] == "github"


# ---------------------------------------------------------------------------
# Tests: search_github_code
# ---------------------------------------------------------------------------

class TestSearchGithubCode:
    @pytest.mark.asyncio
    async def test_returns_results(self):
        json_data = {"items": [{"name": "main.py", "html_url": "https://github.com/user/repo/blob/main.py", "repository": {"full_name": "user/repo"}}]}
        mock_client = make_mock_client("{}", json_data=json_data)
        with patch("mcp_smart_searcher.server.httpx.AsyncClient", return_value=mock_client):
            results = await search_github_code("test", 5)
        assert len(results) == 1
        assert results[0]["title"] == "main.py"
        assert "user/repo" in results[0]["snippet"]
        assert results[0]["engine"] == "github_code"


# ---------------------------------------------------------------------------
# Tests: search_tavily
# ---------------------------------------------------------------------------

class TestSearchTavily:
    @pytest.mark.asyncio
    async def test_no_api_key(self):
        with patch("mcp_smart_searcher.server.TAVILY_API_KEY", ""):
            results = await search_tavily("test", 5)
        assert len(results) == 1
        assert "error" in results[0]

    @pytest.mark.asyncio
    async def test_returns_results_with_answer(self):
        json_data = {"answer": "AI generated answer", "results": [{"title": "Tavily Result", "url": "https://tavily.com", "content": "Content", "score": 0.9}]}
        mock_client = make_mock_client("{}", json_data=json_data)
        with patch("mcp_smart_searcher.server.TAVILY_API_KEY", "test-key"), \
             patch("mcp_smart_searcher.server.httpx.AsyncClient", return_value=mock_client):
            results = await search_tavily("test", 5)
        assert len(results) == 2
        assert results[0]["title"] == "[Tavily AI Answer]"
        assert results[0]["snippet"] == "AI generated answer"
        assert results[1]["title"] == "Tavily Result"


# ---------------------------------------------------------------------------
# Tests: web_search (integration-level with mocked engines)
# ---------------------------------------------------------------------------

class TestWebSearch:
    @pytest.mark.asyncio
    async def test_empty_query(self):
        result = await web_search("")
        assert "Error" in result
        assert "non-empty" in result

    @pytest.mark.asyncio
    async def test_whitespace_query(self):
        result = await web_search("   ")
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_no_allowed_engines(self):
        with patch("mcp_smart_searcher.server.ALLOWED_SEARCH_ENGINES", ["nonexistent"]):
            result = await web_search("test")
        assert "No allowed search engines" in result

    @pytest.mark.asyncio
    async def test_limit_clamping(self):
        """Limit should be clamped between 1 and 50."""
        mock_ddg = AsyncMock(return_value=[])
        with patch.dict("mcp_smart_searcher.server.SEARCH_ENGINES", {"duckduckgo": mock_ddg}, clear=False):
            with patch("mcp_smart_searcher.server.ALLOWED_SEARCH_ENGINES", None):
                result = await web_search("test", engines=["duckduckgo"], limit=0)
                assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_results_formatting(self):
        mock_results = [
            {"title": "Result 1", "url": "https://example.com", "snippet": "Snippet 1", "engine": "duckduckgo"},
            {"title": "Result 2", "url": "https://example2.com", "snippet": "Snippet 2", "engine": "duckduckgo"},
        ]
        mock_ddg = AsyncMock(return_value=mock_results)
        with patch.dict("mcp_smart_searcher.server.SEARCH_ENGINES", {"duckduckgo": mock_ddg}, clear=False):
            with patch("mcp_smart_searcher.server.ALLOWED_SEARCH_ENGINES", None):
                result = await web_search("test", engines=["duckduckgo"])
        assert "[duckduckgo] Result 1" in result
        assert "https://example.com" in result
        assert "Snippet 1" in result

    @pytest.mark.asyncio
    async def test_error_formatting(self):
        mock_results = [{"error": "Simulated failure", "engine": "duckduckgo"}]
        mock_ddg = AsyncMock(return_value=mock_results)
        with patch.dict("mcp_smart_searcher.server.SEARCH_ENGINES", {"duckduckgo": mock_ddg}, clear=False):
            with patch("mcp_smart_searcher.server.ALLOWED_SEARCH_ENGINES", None):
                result = await web_search("test", engines=["duckduckgo"])
        assert "[duckduckgo] Error: Simulated failure" in result


# ---------------------------------------------------------------------------
# Tests: fetch_web_content (integration-level with mocked client)
# ---------------------------------------------------------------------------

class TestFetchWebContent:
    @pytest.mark.asyncio
    async def test_empty_url(self):
        result = await fetch_web_content("")
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_invalid_url(self):
        result = await fetch_web_content("not-a-url")
        assert "Error" in result
        assert "invalid URL" in result

    @pytest.mark.asyncio
    async def test_ftp_url_rejected(self):
        result = await fetch_web_content("ftp://example.com")
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_successful_fetch(self):
        html = "<html><body><article><h1>Title</h1><p>Content here</p></article></body></html>"
        mock_client = make_mock_client(html)
        with patch("mcp_smart_searcher.server.httpx.AsyncClient", return_value=mock_client):
            result = await fetch_web_content("https://example.com")
        assert "Title" in result
        assert "Content here" in result
        assert "URL: https://example.com" in result

    @pytest.mark.asyncio
    async def test_noise_removal(self):
        html = """<html><body>
        <nav>Navigation</nav>
        <script>var x = 1;</script>
        <style>.foo { color: red; }</style>
        <div class="ad-banner">Ad content</div>
        <main><p>Real content</p></main>
        <footer>Footer</footer>
        </body></html>"""
        mock_client = make_mock_client(html)
        with patch("mcp_smart_searcher.server.httpx.AsyncClient", return_value=mock_client):
            result = await fetch_web_content("https://example.com")
        assert "Real content" in result
        assert "Navigation" not in result
        assert "Ad content" not in result
        assert "var x = 1" not in result

    @pytest.mark.asyncio
    async def test_fetch_error(self):
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status = MagicMock(side_effect=httpx.HTTPStatusError("500", request=MagicMock(), response=mock_response))
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch("mcp_smart_searcher.server.httpx.AsyncClient", return_value=mock_client):
            result = await fetch_web_content("https://example.com")
        # 500 errors are retried, final message starts with "Server error"
        assert "Server error 500" in result or "Error" in result


# ---------------------------------------------------------------------------
# Tests: _filter_content_by_prompt
# ---------------------------------------------------------------------------

class TestFilterContentByPrompt:
    def test_empty_prompt_returns_original(self):
        text = "Some content here"
        result = _filter_content_by_prompt(text, "", 1000)
        assert result == text

    def test_keyword_matching(self):
        text = "Python is great for data science.\n\nJavaScript is used for web development.\n\nPython has many libraries for machine learning."
        # Use a small max_chars so only the top-ranked paragraphs fit
        result = _filter_content_by_prompt(text, "python machine learning", 80)
        # Python paragraphs should rank higher
        assert "Python" in result
        assert "JavaScript" not in result

    def test_max_chars_truncation(self):
        long_text = "A" * 5000
        result = _filter_content_by_prompt(long_text, "A", 100)
        assert len(result) <= 100

    def test_no_keywords_match(self):
        text = "Hello world"
        result = _filter_content_by_prompt(text, "xyz abc", 1000)
        # Should still return something (best effort)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# Tests: engine registry consistency
# ---------------------------------------------------------------------------

class TestEngineRegistry:
    def test_all_engines_have_implementations(self):
        """Every engine in ALL_ENGINES must have a SEARCH_ENGINES entry."""
        for engine in ALL_ENGINES:
            assert engine in SEARCH_ENGINES, f"Engine '{engine}' in ALL_ENGINES but not in SEARCH_ENGINES"

    def test_no_extra_engines_in_registry(self):
        """Every engine in SEARCH_ENGINES must be in ALL_ENGINES."""
        for engine in SEARCH_ENGINES:
            assert engine in ALL_ENGINES, f"Engine '{engine}' in SEARCH_ENGINES but not in ALL_ENGINES"


# ---------------------------------------------------------------------------
# Tests: fetch_web_content format modes
# ---------------------------------------------------------------------------

class TestFetchWebContentFormats:
    @pytest.mark.asyncio
    async def test_default_is_markdown(self):
        """Default format should produce Markdown with ATX headings."""
        html = "<html><body><article><h1>Title</h1><p>Content here</p></article></body></html>"
        mock_client = make_mock_client(html)
        with patch("mcp_smart_searcher.server.httpx.AsyncClient", return_value=mock_client):
            result = await fetch_web_content("https://example.com")
        assert "# Title" in result
        assert "Content here" in result

    @pytest.mark.asyncio
    async def test_text_format_legacy_behavior(self):
        """text format should behave like the old plain-text extraction."""
        html = "<html><body><article><h1>Title</h1><p>Content here</p></article></body></html>"
        mock_client = make_mock_client(html)
        with patch("mcp_smart_searcher.server.httpx.AsyncClient", return_value=mock_client):
            result = await fetch_web_content("https://example.com", format="text")
        assert "Title" in result
        assert "Content here" in result
        assert "# Title" not in result  # No Markdown headings in text mode

    @pytest.mark.asyncio
    async def test_markdown_table_preserved(self):
        """Markdown format should preserve tables as Markdown tables."""
        html = """<html><body>
        <table>
            <tr><th>Name</th><th>Age</th></tr>
            <tr><td>Alice</td><td>30</td></tr>
        </table>
        </body></html>"""
        mock_client = make_mock_client(html)
        with patch("mcp_smart_searcher.server.httpx.AsyncClient", return_value=mock_client):
            result = await fetch_web_content("https://example.com", format="markdown")
        assert "| Name |" in result
        assert "| --- |" in result
        assert "| Alice |" in result

    @pytest.mark.asyncio
    async def test_article_format_extracts_body(self):
        """article format should use Readability to extract main content."""
        html = """<html><body>
        <nav>Navigation noise</nav>
        <article><h1>Real Article</h1><p>This is the real content.</p></article>
        <footer>Footer noise</footer>
        </body></html>"""
        mock_client = make_mock_client(html)
        with patch("mcp_smart_searcher.server.httpx.AsyncClient", return_value=mock_client):
            result = await fetch_web_content("https://example.com", format="article")
        assert "Real Article" in result
        assert "This is the real content." in result

    @pytest.mark.asyncio
    async def test_outline_format(self):
        """outline format should return structural overview without full text."""
        html = """<html><head><title>Test Page</title></head><body>
        <main>
            <h1>Main Title</h1>
            <section>
                <h2>Subsection</h2>
                <p>Paragraph text that should NOT appear in outline.</p>
                <a href=\"/a\">Link A</a>
                <a href=\"/b\">Link B</a>
            </section>
        </main>
        </body></html>"""
        mock_client = make_mock_client(html)
        with patch("mcp_smart_searcher.server.httpx.AsyncClient", return_value=mock_client):
            result = await fetch_web_content("https://example.com", format="outline")
        assert "Page Outline" in result
        assert "Main Title" in result
        assert "Subsection" in result
        assert "Paragraph text that should NOT appear in outline." not in result
        assert "2 link" in result

    @pytest.mark.asyncio
    async def test_invalid_format(self):
        """Invalid format should return an error message."""
        mock_client = make_mock_client("<html><body><p>Hi</p></body></html>")
        with patch("mcp_smart_searcher.server.httpx.AsyncClient", return_value=mock_client):
            result = await fetch_web_content("https://example.com", format="xml")
        assert "Error" in result
        assert "invalid format" in result

    @pytest.mark.asyncio
    async def test_prompt_filter_with_markdown(self):
        """prompt filtering should work in markdown mode."""
        html = """<html><body>
        <p>Python is great for data science.</p>
        <p>JavaScript runs in browsers.</p>
        <p>Python has many ML libraries.</p>
        </body></html>"""
        mock_client = make_mock_client(html)
        with patch("mcp_smart_searcher.server.httpx.AsyncClient", return_value=mock_client):
            result = await fetch_web_content(
                "https://example.com",
                format="markdown",
                prompt="python machine learning",
                max_chars=120,
            )
        assert "Python" in result
        assert "JavaScript" not in result
        assert "Extraction prompt: python machine learning" in result

    @pytest.mark.asyncio
    async def test_noise_removal_in_markdown(self):
        """Markdown mode should still remove nav, scripts, ads."""
        html = """<html><body>
        <nav>Navigation</nav>
        <script>var x = 1;</script>
        <div class=\"ad-banner\">Ad content</div>
        <main><h1>Real</h1><p>Real content</p></main>
        <footer>Footer</footer>
        </body></html>"""
        mock_client = make_mock_client(html)
        with patch("mcp_smart_searcher.server.httpx.AsyncClient", return_value=mock_client):
            result = await fetch_web_content("https://example.com", format="markdown")
        assert "Real content" in result
        assert "Navigation" not in result
        assert "Ad content" not in result
        assert "var x = 1" not in result

    @pytest.mark.asyncio
    async def test_hidden_elements_removed(self):
        """Elements with display:none or aria-hidden should be stripped."""
        html = """<html><body>
        <p style=\"display:none\">Hidden by CSS</p>
        <p aria-hidden=\"true\">Aria hidden</p>
        <p>Visible content</p>
        </body></html>"""
        mock_client = make_mock_client(html)
        with patch("mcp_smart_searcher.server.httpx.AsyncClient", return_value=mock_client):
            result = await fetch_web_content("https://example.com", format="markdown")
        assert "Visible content" in result
        assert "Hidden by CSS" not in result
        assert "Aria hidden" not in result


# ---------------------------------------------------------------------------
# Tests: search_brave
# ---------------------------------------------------------------------------

class TestSearchBrave:
    @pytest.mark.asyncio
    async def test_returns_results(self):
        mock_client = make_mock_client(HTML_BRAVE)
        with patch("mcp_smart_searcher.server.httpx.AsyncClient", return_value=mock_client):
            results = await search_brave("test", 5)
        assert len(results) == 2
        assert results[0]["title"] == "Brave Search Result"
        assert results[0]["url"] == "https://example.com/brave-result"
        assert results[0]["snippet"] == "Brave result snippet text here"
        assert results[0]["engine"] == "brave"

    @pytest.mark.asyncio
    async def test_respects_limit(self):
        mock_client = make_mock_client(HTML_BRAVE)
        with patch("mcp_smart_searcher.server.httpx.AsyncClient", return_value=mock_client):
            results = await search_brave("test", 1)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_no_results(self):
        html = "<html><body><p>No results</p></body></html>"
        mock_client = make_mock_client(html)
        with patch("mcp_smart_searcher.server.httpx.AsyncClient", return_value=mock_client):
            results = await search_brave("test", 5)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_error_handling(self):
        """fetch_url returns error string on failure; engine should detect and return error dict."""
        with patch("mcp_smart_searcher.server.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client
            with patch("mcp_smart_searcher.server.fetch_url", return_value="Error fetching https://search.brave.com/search?q=test: TimeoutException"):
                results = await search_brave("test", 5)
        assert len(results) == 1
        assert "error" in results[0]
        assert results[0]["engine"] == "brave"


# ---------------------------------------------------------------------------
# Tests: search_startpage
# ---------------------------------------------------------------------------

class TestSearchStartpage:
    @pytest.mark.asyncio
    async def test_returns_results(self):
        mock_client = make_mock_client(HTML_STARTPAGE)
        with patch("mcp_smart_searcher.server.httpx.AsyncClient", return_value=mock_client):
            results = await search_startpage("test", 5)
        assert len(results) == 2
        assert results[0]["title"] == "Startpage Result Title"
        assert results[0]["url"] == "https://example.com/sp-result"
        assert results[0]["snippet"] == "Startpage result snippet text here"
        assert results[0]["engine"] == "startpage"

    @pytest.mark.asyncio
    async def test_respects_limit(self):
        mock_client = make_mock_client(HTML_STARTPAGE)
        with patch("mcp_smart_searcher.server.httpx.AsyncClient", return_value=mock_client):
            results = await search_startpage("test", 1)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_no_results(self):
        html = "<html><body><p>No results</p></body></html>"
        mock_client = make_mock_client(html)
        with patch("mcp_smart_searcher.server.httpx.AsyncClient", return_value=mock_client):
            results = await search_startpage("test", 5)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_error_handling(self):
        """fetch_url returns error string on failure; engine should detect and return error dict."""
        with patch("mcp_smart_searcher.server.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client
            with patch("mcp_smart_searcher.server.fetch_url", return_value="Error fetching https://www.startpage.com/sp/search?query=test: TimeoutException"):
                results = await search_startpage("test", 5)
        assert len(results) == 1
        assert "error" in results[0]
        assert results[0]["engine"] == "startpage"
