# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**mcp-smart-searcher** is a Python MCP (Model Context Protocol) server that provides multi-engine web search and web content extraction tools for AI agents. Built on FastMCP, it exposes two tools: `web_search` and `fetch_web_content`.

## Architecture

Single-module Python package under `src/mcp_smart_searcher/`:

- **`server.py`** — The entire MCP server. Contains all search engine implementations, the `fetch_url` helper, proxy/allowlist configuration, and the two `@mcp.tool()` handlers.
- **`__init__.py`** — Entry point (`main()`) that parses args and calls `mcp.run()`.
- **`__main__.py`** — Allows `python -m mcp_smart_searcher`.

### Tools Exposed

1. **`web_search(query, engines?, limit?)`** — Parallel search across multiple engines. Supported: `bing`, `duckduckgo`, `brave`, `baidu`, `juejin`, `github`, `github_code`, `tavily`. Engines run concurrently via `asyncio.gather`.
2. **`fetch_web_content(url, prompt?, max_chars?)`** — Fetches a URL, strips noise (scripts, navs, ads, sidebars), extracts main content (prefers `<article>`/`<main>`/`.content`), returns cleaned text.

### Configuration (Environment Variables)

| Variable | Purpose |
|---|---|
| `DEFAULT_SEARCH_ENGINE` | Default engine (default: `bing`) |
| `ALLOWED_SEARCH_ENGINES` | Comma-separated allowlist; unset = all allowed |
| `BRAVE_API_KEY` | Brave Search API key |
| `TAVILY_API_KEY` | Tavily AI Search API key |
| `GITHUB_TOKEN` | GitHub API token (for `github`/`github_code` engines) |
| `USE_PROXY` | Enable proxy (`true`/`false`, default: `false`) |
| `PROXY_URL` | Proxy URL (default: `http://127.0.0.1:7890`) |
| `PROXY_ENGINES` | Comma-separated list of engines that use proxy; unset = all use proxy |

## Build & Development

```bash
# Install dependencies
pip install -e ".[dev]"

# Run the server directly (stdio transport, for MCP clients)
python -m mcp_smart_searcher

# Run with MCP dev inspector
mcp dev src/mcp_smart_searcher/server.py

# Build distribution
pip install build && python -m build

# Run tests
pytest
```

## Key Patterns

- **Proxy config**: `get_proxy_config(engine)` returns `{"proxy": PROXY_URL}` or `{}`. Each search function creates its own `httpx.AsyncClient(**get_proxy_config("engine_name"))` — clients are not shared.
- **Error handling**: Each search engine catches exceptions internally and returns error dicts rather than raising. `fetch_url` retries on timeout (default 2 retries).
- **HTML parsing**: All engines use BeautifulSoup with `lxml` parser. Web content extraction removes noise elements and ad containers by class pattern before extracting text.
