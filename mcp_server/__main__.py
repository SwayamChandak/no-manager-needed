"""
mcp_server/__main__.py — Entry point for Process 1: MCP Server.

Run with:
    python -m mcp_server

Startup sequence:
1. Configure the asyncpg DB pool (lazy — connects on first query).
2. Seed long-term memory in Qdrant (idempotent).
3. Start FastMCP in SSE transport on settings.mcp_server_port.
   The act of importing agent/graph.py (inside mcp_tools.py) calls build_graph()
   which calls load_all_tools() — so the tool registry is populated before any
   graph invocation.
"""

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from config import settings
from db import connection as db_connection
from memory.long_term import seed_memory
from mcp_server.server import mcp


def _seed_memory() -> None:
    try:
        seeded = seed_memory()
        if seeded > 0:
            print(f"[mcp-server] Seeded {seeded} synthetic incidents into Qdrant.")
        else:
            print("[mcp-server] Qdrant already seeded — skipping.")
    except Exception as exc:
        print(f"[mcp-server] Warning: could not seed memory: {exc}")


async def main() -> None:
    if settings.database_url:
        db_connection.configure(settings.database_url)
        print("[mcp-server] DB pool configured.")
    else:
        print("[mcp-server] DATABASE_URL not set — running without DB.")

    _seed_memory()

    print(f"[mcp-server] Starting FastMCP SSE server on port {settings.mcp_server_port}")
    await mcp.run_async(transport="sse", host="0.0.0.0", port=settings.mcp_server_port)


if __name__ == "__main__":
    asyncio.run(main())
