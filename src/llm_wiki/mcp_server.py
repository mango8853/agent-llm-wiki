from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional

from .wiki_backend import WikiBackend, WikiBackendError


def _import_fastmcp():
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise SystemExit(
            "The MCP server requires the optional dependency set. "
            "Install with: python3 -m pip install '.[mcp]'"
        ) from exc
    return FastMCP


_BACKEND: Optional[WikiBackend] = None


def _backend() -> WikiBackend:
    if _BACKEND is None:
        raise WikiBackendError("wiki backend is not initialized")
    return _BACKEND


def create_server():
    FastMCP = _import_fastmcp()
    mcp = FastMCP("llm-wiki")

    @mcp.tool()
    def list_people() -> list[dict]:
        """List every person wiki available under the configured wiki root."""
        return _backend().list_people()

    @mcp.tool()
    def get_index(person_slug: str) -> str:
        """Read the main index page for one person wiki."""
        return _backend().get_index(person_slug)

    @mcp.tool()
    def get_agents_guide(person_slug: str) -> str:
        """Read the AGENTS.md guide for one person wiki."""
        return _backend().get_agents_guide(person_slug)

    @mcp.tool()
    def list_topics(person_slug: str) -> list[dict]:
        """List available topics for one person wiki with statement counts."""
        return _backend().list_topics(person_slug)

    @mcp.tool()
    def get_topic_page(person_slug: str, topic: str) -> str:
        """Read the generated markdown page for one topic."""
        return _backend().get_topic_page(person_slug, topic)

    @mcp.tool()
    def get_topic_statements(person_slug: str, topic: str, limit: int = 20, offset: int = 0) -> dict:
        """Read a paginated structured slice of one topic."""
        return _backend().get_topic_statements(person_slug, topic, limit=limit, offset=offset)

    @mcp.tool()
    def get_timeline(person_slug: str) -> str:
        """Read the timeline page for one person wiki."""
        return _backend().get_timeline(person_slug)

    @mcp.tool()
    def get_sources(person_slug: str) -> str:
        """Read the sources page for one person wiki."""
        return _backend().get_sources(person_slug)

    @mcp.tool()
    def search_statements(person_slug: str, query: str = "", topic: str = "", limit: int = 20, offset: int = 0) -> dict:
        """Search statement previews by substring query and optional topic."""
        return _backend().search_statements(
            person_slug,
            query=query,
            topic=topic or None,
            limit=limit,
            offset=offset,
        )

    @mcp.tool()
    def get_recent_statements(person_slug: str, limit: int = 20, topic: str = "") -> dict:
        """List recent statement previews for one person, optionally filtered by topic."""
        return _backend().get_recent_statements(person_slug, limit=limit, topic=topic or None)

    @mcp.tool()
    def get_statement(person_slug: str, statement_id: str) -> dict:
        """Read one full statement record from the machine-readable metadata store."""
        return _backend().get_statement(person_slug, statement_id)

    return mcp


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="llm-wiki-mcp", description="Read-only MCP server for generated LLM wiki directories.")
    parser.add_argument(
        "--wiki-root",
        type=Path,
        default=Path(os.environ.get("LLM_WIKI_ROOT", "./dist")),
        help="Directory containing built person wiki folders such as dist/yamada-anna.",
    )
    args = parser.parse_args(argv)

    global _BACKEND
    _BACKEND = WikiBackend(args.wiki_root)
    server = create_server()
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
