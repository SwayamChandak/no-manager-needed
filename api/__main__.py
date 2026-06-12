"""
api/__main__.py — Entry point for Process 2: App Server.

Run with:
    python -m api

Startup sequence:
1. Configure the asyncpg DB pool (needed for HITL graph resume via AsyncPostgresSaver).
2. Load tool registry (needed because action_executor runs in this process on HITL resume).
3. Start uvicorn with the combined FastAPI app on settings.app_server_port.
"""

import sys
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn

from config import settings
from db import connection as db_connection
from tools.registry import load_all_tools


def main() -> None:
    if settings.database_url:
        db_connection.configure(settings.database_url)
        print("[app-server] DB pool configured.")
    else:
        print("[app-server] DATABASE_URL not set — HITL resume may not work without DB.")

    load_all_tools()
    print("[app-server] Tool registry loaded.")

    print(f"[app-server] Starting App Server on port {settings.app_server_port}")
    print(f"[app-server] Gradio UI → http://0.0.0.0:{settings.app_server_port}/ui")
    print(f"[app-server] HITL API  → http://0.0.0.0:{settings.app_server_port}/hitl")

    uvicorn.run(
        "api.app:app",
        host="0.0.0.0",
        port=settings.app_server_port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
