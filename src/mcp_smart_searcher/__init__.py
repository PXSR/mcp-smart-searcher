"""
MCP Smart Searcher - A smart MCP server for multi-engine web search with AI-powered results
"""

import argparse

from .server import mcp


def main():
    """Main entry point for the MCP server."""
    parser = argparse.ArgumentParser(
        description="MCP Smart Searcher - Multi-engine web search MCP server with AI-powered results"
    )
    parser.parse_args()

    # Run the FastMCP server
    mcp.run()


__version__ = "0.2.1"
__all__ = ["main", "mcp"]