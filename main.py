"""
main.py — E-Commerce Ops Agent entry point.

Supports two modes via --mode:

  python main.py --mode mcp    (default)
      Starts FastMCP server (stdio, foreground) + HITL FastAPI (background).
      Used for Claude Code / GitHub Copilot MCP client integration.

      MCP client config (.mcp.json):
      {
        "mcpServers": {
          "ecommerce-ops": {
            "command": "python",
            "args": ["main.py"],
            "cwd": "/path/to/store manager"
          }
        }
      }

  python main.py --mode chat
      Starts Gradio chatbot UI on http://localhost:7860 (foreground)
      + HITL FastAPI in background for human-in-the-loop approvals.
"""

import argparse
import asyncio
import threading

import uvicorn

from config import settings
from memory.long_term import seed_memory
from api.hitl_api import hitl_app
from mcp_server.server import mcp


async def start_hitl_server() -> None:
    """Start the HITL FastAPI server (coroutine, used in both modes)."""
    config = uvicorn.Config(
        hitl_app,
        host="0.0.0.0",
        port=settings.hitl_api_port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


def _start_hitl_in_thread() -> None:
    """Launch the HITL server in a daemon background thread with its own event loop.
    Safe to call from a non-async context (i.e. before Gradio's launch())."""
    def _run():
        asyncio.run(start_hitl_server())

    t = threading.Thread(target=_run, daemon=True, name="hitl-server")
    t.start()


def _seed_memory() -> None:
    """Seed long-term memory with synthetic incidents (idempotent)."""
    try:
        seeded = seed_memory()
        if seeded > 0:
            print(f"[startup] Seeded {seeded} synthetic incidents into Qdrant.")
        else:
            print("[startup] Qdrant already seeded — skipping.")
    except Exception as exc:
        print(f"[startup] Warning: could not seed memory: {exc}")


async def run_mcp_mode() -> None:
    """MCP mode: HITL API in background asyncio task, FastMCP server in foreground (stdio)."""
    _seed_memory()

    print("[startup] Mode: MCP")
    print(f"[startup] HITL API  → http://0.0.0.0:{settings.hitl_api_port}")
    print("[startup] MCP server → stdio (connect via .mcp.json)")

    hitl_task = asyncio.create_task(start_hitl_server())
    try:
        await mcp.run_async(transport="stdio")
    finally:
        hitl_task.cancel()
        try:
            await hitl_task
        except asyncio.CancelledError:
            pass


def run_chat_mode() -> None:
    """Chat mode: HITL API in a daemon thread, Gradio UI in the main thread.

    Gradio's launch() must NOT be called inside an asyncio event loop — it
    manages its own threads internally and conflicts with asyncio.run().
    We therefore keep this function synchronous and start HITL via a thread.
    """
    _seed_memory()

    print("[startup] Mode: Chat")
    print("[startup] Gradio UI  → http://localhost:7860")
    print(f"[startup] HITL API  → http://localhost:{settings.hitl_api_port}")

    _start_hitl_in_thread()

    # Import lazily so MCP mode works even without gradio installed
    from ui.chatbot import demo
    demo.launch(server_name="0.0.0.0", server_port=7860, share=False)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="E-Commerce Ops Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--mode",
        choices=["mcp", "chat"],
        default="mcp",
        help="Run mode: 'mcp' (default) for FastMCP+HITL, 'chat' for Gradio UI+HITL",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.mode == "chat":
        run_chat_mode()
    else:
        asyncio.run(run_mcp_mode())
