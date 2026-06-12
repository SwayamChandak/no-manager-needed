# Change Plan: Tool Safety, Authorization, Discovery & Architecture Refactor

## Overview

| # | Change | Scope |
|---|---|---|
| 1 | Async error isolation — buggy tools cannot crash the agent process | tools |
| 2 | Per-agent authorization — agents cannot call tools outside their domain | tools, specialists, action_executor.py |
| 3 | Startup tool discovery — new tool files picked up without code changes | `tools/registry.py`, startup hooks |
| 4 | Two-process architecture: MCP Server + App Server (chat-only mode) | mcp_server, api, ui, main.py |
| 5 | Agents discover tools from registry at runtime — no hardcoded imports | `agent/specialists/*.py`, action_executor.py |

Changes 1, 2, 3, and 5 are tightly coupled and implemented together via a single registry module. Change 4 is independent but depends on 1–3 being complete first (both processes share the same startup hook).

---

## Changes 1–3 & 5: Tool Registry System

### New File: `tools/registry.py`

Three public functions:

```python
def safe_tool(agents: list[str], timeout_seconds: float | None = None):
    """
    Decorator. Does three things in one pass:
    1. Wraps the async tool body in try/except + optional asyncio.wait_for(timeout).
       On any exception or timeout, returns {"error": "..."} — never raises. (Change 1)
    2. Registers the resulting LangChain BaseTool in _REGISTRY under each agent name.
       Only agents listed in `agents` can retrieve this tool. (Change 2)
    3. Converts the function to a LangChain BaseTool via @langchain_tool.
    """

def get_tools_for_agent(agent_name: str) -> list[BaseTool]:
    """Returns authorized tools for the named agent. (Changes 2 & 5)"""

def load_all_tools() -> None:
    """
    Uses pkgutil.iter_modules to find every .py file in the tools/ package,
    then importlib.import_module("tools.<name>") each one.
    The act of importing fires @safe_tool decorators, populating _REGISTRY.
    Skips: registry.py, __init__.py.
    Called once at process startup. (Change 3)
    """
```

### How `safe_tool` Works Internally

```python
# Conceptual — this is the plan, not the final code

_REGISTRY: dict[str, list] = {}

def safe_tool(agents: list[str], timeout_seconds: float | None = None):
    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            try:
                coro = fn(*args, **kwargs)
                if timeout_seconds is not None:
                    return await asyncio.wait_for(coro, timeout=timeout_seconds)
                return await coro
            except asyncio.TimeoutError:
                return {"error": f"Tool '{fn.__name__}' timed out after {timeout_seconds}s"}
            except Exception as e:
                return {"error": f"Tool '{fn.__name__}' failed: {type(e).__name__}: {e}"}

        lc_tool = langchain_tool(wrapper)
        for agent in agents:
            _REGISTRY.setdefault(agent, []).append(lc_tool)
        return lc_tool
    return decorator
```

The ReAct agent receives `{"error": "..."}` as a tool observation and can reason about it. No exception propagates to the specialist node.

### Authorization Enforcement

`get_tools_for_agent("inventory")` returns only tools registered with `agents=["inventory", ...]`. There is no mechanism for one specialist to obtain another specialist's tools without a deliberate code change.

Write tools in actions.py are registered under `agents=["action_executor"]` — invisible to all four read-only specialists.

### Tool File Changes

| File | Current | New |
|---|---|---|
| analytics.py | `@tool` | `@safe_tool(agents=["sales"])` |
| inventory.py | `@tool` | `@safe_tool(agents=["inventory"])` |
| campaigns.py | `@tool` | `@safe_tool(agents=["marketing"])` |
| crm.py | `@tool` | `@safe_tool(agents=["support"])` |
| actions.py | `@tool` | `@safe_tool(agents=["action_executor"])` |

The import at the top of each file changes from `from langchain.tools import tool` to `from tools.registry import safe_tool`. No other changes to tool function bodies.

### Specialist File Changes (Change 5)

**Before (sales.py):**
```python
from tools.analytics import (
    detect_anomaly, get_order_volume, get_revenue_by_product,
    get_revenue_by_region, get_revenue_timeseries,
)
sales_tools = [get_revenue_timeseries, ...]
```

**After:**
```python
from tools.registry import get_tools_for_agent
# No direct tool imports — registry is the only source
```

Inside `run_sales_agent()`, replace `sales_tools` with `get_tools_for_agent("sales")`.

Same pattern for `inventory.py`, `marketing.py`, `support.py`, and `action_executor.py`.

In `action_executor.py`, the hardcoded `ACTION_TOOL_MAP` dict is replaced by building it dynamically from `get_tools_for_agent("action_executor")`, keyed by `tool.name`.

### Adding a New Tool After Implementation

1. Create `tools/<new_file>.py`
2. `from tools.registry import safe_tool`
3. Decorate: `@safe_tool(agents=["<target_agent>"])`
4. Restart the relevant process

**Zero changes to any other file.**

---

## Change 4: Two-Process Architecture

### Current Architecture (removed)

```
python main.py --mode mcp    → FastMCP stdio + HITL FastAPI (background thread)
python main.py --mode chat   → Gradio (foreground) + HITL FastAPI (background thread)
ui/chatbot.py calls graph.astream_events() directly (in-process)
```

### New Architecture

```
┌─────────────────────────────────────────────────────┐
│              Process 2: App Server (:8001)           │
│                                                      │
│  Gradio UI  ──→  FastAPI                            │
│                      │                              │
│               MCP Client (SSE)                      │
│                      │  MCP protocol                │
└──────────────────────┼──────────────────────────────┘
                       │
┌──────────────────────┼──────────────────────────────┐
│              Process 1: MCP Server (:8000)           │
│                      │                              │
│              FastMCP (SSE transport)                │
│              graph.ainvoke() / graph.astream()      │
│              AsyncPostgresSaver (shared checkpoint) │
└─────────────────────────────────────────────────────┘
                       │
              PostgreSQL (shared by both processes)
```

### The HITL Cross-Process Problem and Solution

The graph's checkpoint store must be accessible to whichever process calls `graph.get_state()` and `graph.astream(Command(resume=...))`. `MemorySaver` is in-memory, bound to a single process — it cannot be shared.

**Solution: `AsyncPostgresSaver` is mandatory for two-process mode.**

Both processes import graph.py. Because `AsyncPostgresSaver` is backed by the shared PostgreSQL instance already in the project, both processes share the same checkpoint state. The App Server's HITL endpoints call `graph.astream(Command(resume=...))` directly — same code as today, no proxying required.

The `checkpoint_backend` config setting changes from `"memory"` (current default) to `"postgres"`. The `MemorySaver` code path in graph.py can remain for local unit testing.

### New Config Settings (config.py)

```python
mcp_server_port: int = 8000
app_server_port: int = 8001
mcp_server_url: str = "http://localhost:8000/sse"
```

### Process 1: MCP Server

**New file: `mcp_server/__main__.py`**

Startup sequence:
1. `db_connection.configure(settings.database_url)`
2. `load_all_tools()` — populates registry (tools used by graph nodes in this process)
3. `await seed_memory()`
4. `mcp.run(transport="sse", port=settings.mcp_server_port)`

**Changes to server.py:**
- Add `mcp.run(transport="sse", port=settings.mcp_server_port)`
- Move startup logic out (into `__main__.py`)
- No HITL FastAPI in this process

The four MCP tools in mcp_tools.py are unchanged.

**Run:** `python -m mcp_server`

### Process 2: App Server

**New file: `api/app.py`** — a single FastAPI application combining:
- Gradio UI mounted at `/` via `gr.mount_gradio_app`
- Existing HITL endpoints (`/hitl/pending`, `/hitl/approve/{session_id}`, `/hitl/reject/{session_id}`) — logic unchanged
- Chat proxy endpoint `POST /chat` that calls the MCP Server via MCP client

```python
# Conceptual — verify actual fastmcp client API before implementation
from fastmcp import Client as MCPClient

mcp_client = MCPClient(settings.mcp_server_url)

@app.post("/chat")
async def chat(request: ChatRequest):
    # request.intent is one of: diagnose, fix, recall, summarize
    result = await mcp_client.call_tool(
        request.intent,
        {"question": request.message, "session_id": request.session_id}
    )
    return result
```

**New file: `api/__main__.py`**

Startup sequence:
1. `db_connection.configure(settings.database_url)`
2. `load_all_tools()` — needed because `action_executor` runs in this process during HITL resumes
3. `uvicorn.run(app, host="0.0.0.0", port=settings.app_server_port)`

**Run:** `python -m api`

### Changes to chatbot.py

**Before:** `gr.ChatInterface` callback calls `graph.astream_events()` directly.

**After:** callback sends `POST /chat` to the App Server via `httpx.AsyncClient`. The Gradio app object is imported by `api/app.py` and mounted there — chatbot.py no longer calls `gr.launch()` itself. The HITL approval panel continues calling `/hitl/approve/{session_id}` — same URL, no change.

### main.py Disposition

Removed. Both processes have dedicated `__main__.py` entry points. An optional dev convenience wrapper can be kept to `subprocess.Popen` both processes together, but it is not part of the core architecture.

---

## Implementation Order

| Step | File(s) | What | Depends On |
|---|---|---|---|
| 1 | `tools/registry.py` (create) | `safe_tool`, `get_tools_for_agent`, `load_all_tools`, `_REGISTRY` | — |
| 2 | All 5 files in tools | `@tool` → `@safe_tool(agents=[...])` | Step 1 |
| 3 | `agent/specialists/*.py` | Remove direct imports; call `get_tools_for_agent` inside node | Step 2 |
| 4 | action_executor.py | Build `ACTION_TOOL_MAP` dynamically from registry | Step 2 |
| 5 | config.py | Add `mcp_server_port`, `app_server_port`, `mcp_server_url` | — |
| 6 | graph.py | Switch to `AsyncPostgresSaver`; keep `MemorySaver` for test mode | Step 5 |
| 7 | server.py | Move startup logic out; add SSE transport | Step 5 |
| 8 | `mcp_server/__main__.py` (create) | Process 1 entry point | Steps 1, 5, 7 |
| 9 | `api/app.py` (create) | Combined FastAPI: Gradio + HITL + `/chat` MCP proxy | Steps 5, 6 |
| 10 | chatbot.py | Replace `graph.astream_events()` with `httpx` calls; remove `gr.launch()` | Step 9 |
| 11 | `api/__main__.py` (create) | Process 2 entry point | Steps 1, 5, 9 |
| 12 | requirements.txt | Add `fastmcp[client]`, `httpx` | — |
| 13 | main.py | Remove or repurpose as optional dev wrapper | Steps 8, 11 |

---

## Complete File Impact Summary

| File | Action | Change |
|---|---|---|
| `tools/registry.py` | **Create** | Registry, `safe_tool`, `load_all_tools`, `get_tools_for_agent` |
| analytics.py | Modify | `@tool` → `@safe_tool(agents=["sales"])` |
| inventory.py | Modify | `@tool` → `@safe_tool(agents=["inventory"])` |
| campaigns.py | Modify | `@tool` → `@safe_tool(agents=["marketing"])` |
| crm.py | Modify | `@tool` → `@safe_tool(agents=["support"])` |
| actions.py | Modify | `@tool` → `@safe_tool(agents=["action_executor"])` |
| sales.py | Modify | Remove 5 tool imports; use `get_tools_for_agent("sales")` |
| inventory.py | Modify | Same pattern |
| marketing.py | Modify | Same pattern |
| support.py | Modify | Same pattern |
| action_executor.py | Modify | Build `ACTION_TOOL_MAP` from `get_tools_for_agent("action_executor")` |
| graph.py | Modify | Switch to `AsyncPostgresSaver`; keep `MemorySaver` fallback |
| config.py | Modify | Add 3 new settings |
| server.py | Modify | SSE transport; remove startup logic |
| `mcp_server/__main__.py` | **Create** | Process 1 entry point |
| `api/app.py` | **Create** | Combined FastAPI app |
| `api/__main__.py` | **Create** | Process 2 entry point |
| chatbot.py | Modify | `httpx` calls to App Server; remove `gr.launch()` |
| requirements.txt | Modify | `fastmcp[client]`, `httpx` |
| main.py | **Remove** | Superseded |

**New: 4 files. Modified: 15 files. Removed: 1 file.**

---

## Risks

| Risk | Mitigation |
|---|---|
| `AsyncPostgresSaver` needs LangGraph checkpoint tables in the database | Run `AsyncPostgresSaver.setup()` in migrate.py — it creates tables if absent |
| `fastmcp.Client` SSE API may differ from what's shown above | Verify actual API from installed package before implementing Step 9 |
| `gr.mount_gradio_app` requires Gradio ≥ 4.x | Verify version in requirements.txt before Step 9 |
| Both processes call `load_all_tools()` — registry is per-process | Correct and expected — each process needs its own in-memory registry |