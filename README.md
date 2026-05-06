# MCP Smart Searcher

A smart MCP (Model Context Protocol) server for multi-engine web search with AI-powered results.

## Features

- **Multi-engine search** — Search across 6 engines simultaneously: DuckDuckGo, Baidu, Juejin, GitHub, GitHub Code, Tavily
- **Web content extraction** — Fetch and extract clean text from any public URL, with noise removal and prompt-guided filtering
- **Rate limiting** — Built-in concurrency control via semaphore
- **Proxy support** — Per-engine proxy configuration
- **Engine allowlist** — Restrict which engines can be used

## Installation

```bash
pip install -e ".[dev]"
```

## Usage

### Run the server

```bash
python -m mcp_smart_searcher
```

### MCP client configuration

Add to your MCP client config (e.g., Claude Desktop):

```json
{
  "mcpServers": {
    "smart-searcher": {
      "command": "python",
      "args": ["-m", "mcp_smart_searcher"]
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

| Environment Variable | Description | Default |
|---|---|---|
| `DEFAULT_SEARCH_ENGINE` | Default search engine | `duckduckgo` |
| `ALLOWED_SEARCH_ENGINES` | Comma-separated engine allowlist | (all allowed) |
| `TAVILY_API_KEY` | Tavily AI Search API key | (none) |
| `GITHUB_TOKEN` | GitHub API token | (none) |
| `USE_PROXY` | Enable proxy | `true` |
| `PROXY_URL` | Proxy URL | `http://127.0.0.1:7890` |
| `PROXY_ENGINES` | Comma-separated engines using proxy | (all) |
| `MAX_CONCURRENT_SEARCH` | Max concurrent search requests | `5` |
| `LOG_LEVEL` | Logging level | `INFO` |

## License

Apache-2.0
