# MCP Smart Searcher

A smart MCP (Model Context Protocol) server for multi-engine web search with AI-powered results.

## Features

- **Multi-engine search** — Search across 8 engines simultaneously: DuckDuckGo, Baidu, Juejin, GitHub, GitHub Code, Tavily, Brave, Startpage
- **Web content extraction** — Fetch and extract clean content from any public URL in multiple formats:
  - `markdown` (default) — Structured Markdown with headings, lists, code blocks, tables, and links preserved
  - `article` — Reader-mode extraction via Mozilla Readability, ideal for blogs/docs/news
  - `text` — Plain text, legacy behavior
  - `outline` — Page structure overview (headings, regions, interactive elements) without full content
  - Plus noise removal, hidden-element stripping, and prompt-guided filtering
- **Rate limiting** — Built-in concurrency control via semaphore
- **Proxy support** — Per-engine proxy configuration
- **Engine allowlist** — Restrict which engines can be used

## Installation

```bash
# For users
pip install mcp-smart-searcher

# For development
pip install -e ".[dev]"
```

## Usage

### Run the server

```bash
# Direct command (after pip install)
mcp-smart-searcher

# Or via Python module
python -m mcp_smart_searcher

# Or via uvx (no install required)
uvx mcp-smart-searcher
```

### MCP client configuration

Add to your MCP client config (e.g., Claude Desktop):

```json
{
  "mcpServers": {
    "smart-searcher": {
      "command": "mcp-smart-searcher"
    }
  }
}
```

Or with `uvx` (no install required):

```json
{
  "mcpServers": {
    "smart-searcher": {
      "command": "uvx",
      "args": ["mcp-smart-searcher"]
    }
  }
}
```

### Development

```bash
# Run with MCP inspector
mcp dev src/mcp_smart_searcher/server.py

# Run tests
PYTHONPATH=src pytest

# Build
python -m build
```

## Configuration

All settings are configured via environment variables:

| Variable | Description | Default |
|---|---|---|
| `DEFAULT_SEARCH_ENGINES` | Comma-separated default engines when none specified | `duckduckgo,baidu,startpage,tavily,brave` |
| `ALLOWED_SEARCH_ENGINES` | Comma-separated allowlist; unset = all allowed | (all) |
| `TAVILY_API_KEY` | Tavily AI Search API key | (none) |
| `GITHUB_TOKEN` | GitHub API token (for github/github_code engines) | (none) |
| `USE_PROXY` | Enable proxy for engines that need it | `true` |
| `PROXY_URL` | Proxy address | `http://127.0.0.1:10809` |
| `PROXY_ENGINES` | Override: comma-separated engines that use proxy | (auto) |
| `MAX_CONCURRENT_SEARCH` | Max parallel search requests | `5` |
| `LOG_LEVEL` | Logging level (`DEBUG`/`INFO`/`WARNING`/`ERROR`) | `INFO` |

### Proxy behavior

By default, domestic engines (`baidu`, `juejin`) skip proxy, while all others use proxy. You can override this with `PROXY_ENGINES`:

```bash
# Only use proxy for DuckDuckGo and GitHub
PROXY_ENGINES=duckduckgo,github,github_code

# Disable proxy entirely
USE_PROXY=false
```

### MCP client configuration with env vars

```json
{
  "mcpServers": {
    "smart-searcher": {
      "command": "mcp-smart-searcher",
      "env": {
        "TAVILY_API_KEY": "tvly-xxx",
        "GITHUB_TOKEN": "ghp_xxx",
        "PROXY_URL": "http://127.0.0.1:10809",
        "LOG_LEVEL": "INFO"
      }
    }
  }
}
```

Or with `uvx` (no install required):

```json
{
  "mcpServers": {
    "smart-searcher": {
      "command": "uvx",
      "args": ["mcp-smart-searcher"],
      "env": {
        "TAVILY_API_KEY": "tvly-xxx",
        "GITHUB_TOKEN": "ghp_xxx"
      }
    }
  }
}
```

## Quick Start

### 1. Install

```bash
pip install mcp-smart-searcher
```

### 2. Configure (optional)

Create a `.env` file or set environment variables:

```bash
# .env
TAVILY_API_KEY=tvly-your-key-here
GITHUB_TOKEN=ghp_your-token-here
PROXY_URL=http://127.0.0.1:10809
LOG_LEVEL=INFO
```

### 3. Add to your MCP client

```json
{
  "mcpServers": {
    "smart-searcher": {
      "command": "mcp-smart-searcher"
    }
  }
}
```

### 4. Done!

Your AI agent can now search the web and fetch web pages.

## License

Apache-2.0
