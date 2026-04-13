"""
OncoCITE Model Context Protocol (MCP) server package.

Exposes the 22 specialized tools listed in Supplementary Table S15 of the
manuscript over MCP stdio transport, so MCP-compatible clients (Claude
Desktop, inspector tools, other LLM agents) can drive the extraction
pipeline end-to-end.

Run with `python -m mcp_server` or `uv run python -m mcp_server`.
"""

from .server import build_server, main

__all__ = ["build_server", "main"]
