# HITL UI Implementation Plan

**Project:** E-Commerce AI Ops Agent  
**Authors:** Technical Architecture Team  
**Date:** 2026-06-08  
**Status:** Draft — Ready for Implementation

---

## Table of Contents

1. [Goal](#1-goal)
2. [Architecture Overview](#2-architecture-overview)
3. [Bugs to Fix First (Prerequisites)](#3-bugs-to-fix-first-prerequisites)
4. [Implementation Steps](#4-implementation-steps)
5. [File Change Summary Table](#5-file-change-summary-table)
6. [Non-Goals / Out of Scope](#6-non-goals--out-of-scope)

---

## 1. Goal

Add a **per-action approve/reject panel** inside the Gradio chatbot UI so that operators can review each proposed fix action individually, selectively approve a subset, and confirm or reject the plan — all without leaving the chat interface or touching a REST client like `curl`.

Currently, when the LangGraph graph suspends at the `hitl_node` interrupt checkpoint, the chatbot displays a plain-text message instructing the user to manually call `POST /hitl/approve/{session_id}` via HTTP. This is impractical for non-technical operators and defeats the purpose of a conversational interface.

After this implementation:

- The chat UI will **automatically display an approval panel** whenever the graph suspends for HITL.
- The panel will show one row per proposed action, with each action's `action_type`, `estimated_impact`, and `justification`.
- A **checkbox per action** (default: checked = approved) allows the operator to deselect individual actions they do not want executed.
- A **"Confirm Selections"** button submits the approved subset back to the graph.
- A **"Reject All"** button rejects the entire plan without executing anything.
- After the decision, the graph resumes, executes only the approved actions, returns its final response, and the approval panel disappears.

---

## 2. Architecture Overview

### End-to-End Flow

1. The operator types a message with "fix" intent (e.g., *"Restock product P001 and pause underperforming campaign C002"*).
2. The chatbot calls `graph.astream(initial_state, config)`.
3. LangGraph executes: `orchestrator_node` → specialist nodes (parallel fan-out via `Send()`) → `aggregator_node` → `reflection_node`.
4. `route_after_reflection` routes to `hitl_node`.
5. `hitl_node` calls `interrupt()`, suspending the graph. `graph.astream()` completes its iteration.
6. `chat_fn` (the renamed streaming function) calls `graph.get_state(config)` and detects `snapshot.next` is non-empty.
7. It extracts `proposed_actions` from the snapshot, calls `hitl_store.register()` on the shared store, and yields 5 outputs including the populated `proposed_actions_state` and `hitl_pending_state=True`.
8. Gradio updates the UI: the HITL approval panel becomes **visible**. The `gr.CheckboxGroup` is populated with one entry per proposed action (all pre-checked).
9. The operator reviews the actions, unchecks any they want to skip, and clicks **"Confirm Selections"**.
10. `handle_approve()` is called with `session_id`, `proposed_actions`, and the list of selected action labels.
11. It filters `proposed_actions` to only the checked ones, then calls `await graph.ainvoke(Command(resume={"approved": True, "modified_actions": filtered_actions}), config=config)`.
12. The graph resumes: `hitl_node` returns the approved subset → `route_after_hitl` routes to `action_executor_node` → `output_formatter_node`.
13. `handle_approve()` updates the chat history with the final response, clears all HITL state, and sets the panel to `visible=False`.
14. Alternatively, the operator clicks **"Reject All"**: `handle_reject()` calls `await graph.ainvoke(Command(resume={"approved": False}), config=config)`. The graph sets `approved_actions=[]` and routes through `action_executor_node` with nothing to execute.

### Component Responsibilities After This Change

| Component | Responsibility |
|---|---|
| `api/hitl_store.py` (new) | Single source of truth for pending HITL sessions. Thread-safe wrapper around a plain dict. |
| `api/hitl_api.py` | REST API for external callers. Imports from `hitl_store.py`. Uses `await graph.ainvoke()`. |
| `mcp_server/mcp_tools.py` | MCP fix tool. Imports from `hitl_store.py` instead of its own local dict. |
| `ui/chatbot.py` | Gradio UI. Manages HITL panel visibility via `gr.State`. Calls `graph.ainvoke` directly on approve/reject. |
| `agent/hitl.py` | Async LangGraph node. Calls `interrupt()`, processes the approval payload on resume. |
| `agent/graph.py` | No changes needed. Routing logic is unchanged. |

---

## 3. Bugs to Fix First (Prerequisites)

All six bugs below must be fixed **before** implementing the new HITL UI panel.

---

### Bug 1 — `api/hitl_api.py`: Blocking `graph.invoke()` in async FastAPI handlers

**File:** `api/hitl_api.py`  
**Functions affected:** `approve()`, `reject()`, `modify_and_approve()`

**Problem:**  
All three action endpoints are declared `async def` but call `graph.invoke(Command(resume=...))`, which is the synchronous variant of the LangGraph invocation API. Calling a blocking synchronous operation inside an async function without offloading to a thread pool blocks the FastAPI/Uvicorn event loop for the entire duration of graph execution — which involves LLM calls and can take many seconds. During that time, FastAPI cannot service any other incoming requests, causing cascading timeouts for all concurrent API callers.

**Current code (example from `approve`):**
```python
graph.invoke(Command(resume=approval_payload), config=config)
```

**Fix:**  
Replace every occurrence of `graph.invoke(...)` with `await graph.ainvoke(...)` in all three endpoints:
```python
await graph.ainvoke(Command(resume=approval_payload), config=config)
```

---

### Bug 2 — `ui/chatbot.py`: `session_id` not persisted in Gradio state

**File:** `ui/chatbot.py`  
**Function affected:** `chat_stream()` generator and event wiring

**Problem:**  
`session_id` is created as a local variable inside the `chat_stream()` async generator. It exists only for the lifetime of that generator call. The Gradio UI has no `gr.State()` component to persist it across the component boundary. When approve/reject buttons are added, their click handlers will have no way to reference the `session_id` of the currently suspended session.

Similarly, `proposed_actions` and a `hitl_pending` boolean flag are computed inside the generator but never surfaced to the Gradio state layer.

**Fix:**  
Add three `gr.State()` components to the Gradio `Blocks` layout:
```python
session_id_state = gr.State(value="")
proposed_actions_state = gr.State(value=[])
hitl_pending_state = gr.State(value=False)
```
Update `chat_fn` (the renamed generator) to yield **5 outputs** instead of 2 on every code path.

---

### Bug 3 — Dual disconnected HITL in-memory stores

**Files:** `api/hitl_api.py` and `mcp_server/mcp_tools.py`

**Problem:**  
There are two completely separate in-memory dictionaries tracking pending HITL sessions:

- `api/hitl_api.py` declares `_pending_sessions: dict[str, dict] = {}` at module level.
- `mcp_server/mcp_tools.py` declares `_hitl_pending: dict[str, dict] = {}` at module level.

These two dicts are never synchronized. Sessions initiated via different entry points are invisible to each other's tracking stores.

**Fix:**  
Create `api/hitl_store.py` with a `HITLStore` class (see Step 1). Both modules import and use the singleton instance from this module.

---

### Bug 4 — `ui/chatbot.py`: No HITL UI panel

**File:** `ui/chatbot.py`

**Problem:**  
There are no Gradio components for HITL interaction. When the graph suspends, the chatbot renders a plain-text block with API endpoint URLs. The operator must manually call the REST API via `curl`.

**Fix:**  
Add a `gr.Column(visible=False)` HITL panel below the chatbot with a `gr.CheckboxGroup`, a "Confirm Selections" button, and a "Reject All" button. Panel visibility is controlled reactively by `hitl_pending_state`. See Step 4.

---

### Bug 5 — `agent/hitl.py`: Synchronous node in an async graph

**File:** `agent/hitl.py`  
**Function affected:** `def run_hitl(state: OpsAgentState) -> dict:`

**Problem:**  
`run_hitl` is a synchronous function in a graph invoked via `graph.astream()` and `graph.ainvoke()`. LangGraph bridges sync nodes internally, but this is problematic with async checkpointers and inconsistent with the async invocation pattern used everywhere else.

**Fix:**
```python
# Before
def run_hitl(state: OpsAgentState) -> dict:

# After
async def run_hitl(state: OpsAgentState) -> dict:
```
No body changes needed.

---

### Bug 6 — `ui/chatbot.py`: Output arity mismatch after adding HITL panel

**File:** `ui/chatbot.py`

**Problem:**  
Once `gr.State()` components are added, every `yield` in `chat_fn` must yield exactly 5 values, and every `.click()` / `.submit()` must list all 5 in `outputs`. There are currently four yield sites in `chat_stream`. Missing any update causes a Gradio `ValueError: Number of outputs does not match...` at runtime.

**Fix:** Update all four yield sites and all event wiring as part of Steps 3 and 6.

---

## 4. Implementation Steps

### Step 1: Create Shared HITL Store (`api/hitl_store.py`)

Create a new file `api/hitl_store.py`:

```python
"""
api/hitl_store.py — Centralized in-memory store for pending HITL sessions.

Both api/hitl_api.py and mcp_server/mcp_tools.py import the singleton
`hitl_store` from this module. This eliminates the dual-store bug.
"""

import threading
from datetime import datetime
from typing import Any


class HITLStore:
    """Thread-safe in-memory store for sessions suspended at the HITL interrupt."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, dict[str, Any]] = {}

    def register(self, session_id: str, proposed_actions: list[dict]) -> None:
        with self._lock:
            self._sessions[session_id] = {
                "proposed_actions": proposed_actions,
                "registered_at": datetime.utcnow().isoformat(),
            }

    def get(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._sessions.get(session_id)

    def remove(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def list_pending(self) -> list[str]:
        with self._lock:
            return list(self._sessions.keys())


hitl_store = HITLStore()
```

Then update the three consumers:

- **`api/hitl_api.py`**: Remove `_pending_sessions` dict and `register_pending_session()`. Add `from api.hitl_store import hitl_store`. Replace all `_pending_sessions` usages with `hitl_store` method calls.
- **`mcp_server/mcp_tools.py`**: Remove `_hitl_pending` dict. Add `from api.hitl_store import hitl_store`. Replace all `_hitl_pending` usages with `hitl_store.register()` / `hitl_store.remove()`.
- **`ui/chatbot.py`**: Replace `from api.hitl_api import register_pending_session` with `from api.hitl_store import hitl_store`.

---

### Step 2: Fix `api/hitl_api.py` Async Bug

Change `graph.invoke(...)` → `await graph.ainvoke(...)` in the `approve()`, `reject()`, and `modify_and_approve()` endpoints. Three call sites total.

---

### Step 3: Update `ui/chatbot.py` — State Management

Add three `gr.State()` components inside `gr.Blocks(...)`:

```python
session_id_state = gr.State(value="")
proposed_actions_state = gr.State(value=[])
hitl_pending_state = gr.State(value=False)
```

Rename `chat_stream` → `chat_fn`. Extend its signature to accept three additional state inputs. Update all four `yield` sites to yield 5 outputs:
- `(history, log_text, session_id, proposed_actions, hitl_pending)`
- On the interrupt-detection branch: populate `session_id` and `proposed_actions` with real values, set `hitl_pending=True`.
- On all other branches: yield `""`, `[]`, `False` for the three new slots.

---

### Step 4: Update `ui/chatbot.py` — HITL UI Panel

Add a hidden panel after the main chat row inside `gr.Blocks(...)`:

```python
with gr.Column(visible=False) as hitl_panel:
    gr.Markdown("## Human Approval Required")
    gr.Markdown(
        "Review each proposed action. Uncheck any you want to skip, then confirm."
    )
    action_checkbox_group = gr.CheckboxGroup(
        choices=[],
        value=[],
        label="Proposed Actions — uncheck to exclude from execution",
        interactive=True,
    )
    with gr.Row():
        confirm_btn = gr.Button("Confirm Selections", variant="primary")
        reject_btn = gr.Button("Reject All", variant="stop")
```

Add reactive helpers:

```python
def _build_action_labels(proposed_actions):
    labels = []
    for i, action in enumerate(proposed_actions):
        label = (
            f"{action.get('action_type', f'action_{i}')} | "
            f"Impact: {action.get('estimated_impact', '')} | "
            f"{action.get('justification', '')[:80]}"
        )
        labels.append(label)
    return labels, labels  # (choices, all pre-selected)


def _on_hitl_state_change(proposed_actions, hitl_pending):
    if hitl_pending and proposed_actions:
        choices, default_value = _build_action_labels(proposed_actions)
        return gr.update(choices=choices, value=default_value), gr.update(visible=True)
    return gr.update(choices=[], value=[]), gr.update(visible=False)


hitl_pending_state.change(
    fn=_on_hitl_state_change,
    inputs=[proposed_actions_state, hitl_pending_state],
    outputs=[action_checkbox_group, hitl_panel],
)
```

---

### Step 5: Add Approve/Reject Handler Functions in `ui/chatbot.py`

Add `from langgraph.types import Command` at the top.

**`handle_approve(session_id, proposed_actions, selected_labels, history, log_text)`** (async generator):
1. Rebuild the label→action mapping using the same label format as `_build_action_labels`.
2. Filter `proposed_actions` to only those whose label is in `selected_labels`.
3. Call `await graph.ainvoke(Command(resume={"approved": True, "modified_actions": filtered or None}), config=config)`.
4. Call `hitl_store.remove(session_id)`.
5. Append the final response to history.
6. `yield (history, log, "", [], False, gr.update(visible=False))` — 6 outputs.

**`handle_reject(session_id, history, log_text)`** (async generator):
1. Call `await graph.ainvoke(Command(resume={"approved": False}), config=config)`.
2. Call `hitl_store.remove(session_id)`.
3. Append rejection confirmation to history.
4. `yield (history, log, "", [], False, gr.update(visible=False))` — 6 outputs.

---

### Step 6: Wire the New Components

Replace all existing `.click()` / `.submit()` wiring:

```python
# Chat submission
send_btn.click(
    fn=chat_fn,
    inputs=[msg_box, chatbot, log_box, session_id_state, proposed_actions_state, hitl_pending_state],
    outputs=[chatbot, log_box, session_id_state, proposed_actions_state, hitl_pending_state],
).then(lambda: "", outputs=msg_box)

msg_box.submit(
    fn=chat_fn,
    inputs=[msg_box, chatbot, log_box, session_id_state, proposed_actions_state, hitl_pending_state],
    outputs=[chatbot, log_box, session_id_state, proposed_actions_state, hitl_pending_state],
).then(lambda: "", outputs=msg_box)

# Clear button
clear_btn.click(
    fn=lambda: ([], "Waiting for query...", "", [], False),
    outputs=[chatbot, log_box, session_id_state, proposed_actions_state, hitl_pending_state],
)

# HITL buttons
confirm_btn.click(
    fn=handle_approve,
    inputs=[session_id_state, proposed_actions_state, action_checkbox_group, chatbot, log_box],
    outputs=[chatbot, log_box, session_id_state, proposed_actions_state, hitl_pending_state, hitl_panel],
)

reject_btn.click(
    fn=handle_reject,
    inputs=[session_id_state, chatbot, log_box],
    outputs=[chatbot, log_box, session_id_state, proposed_actions_state, hitl_pending_state, hitl_panel],
)
```

**Output arity reference:**

| Event handler | # outputs | outputs list |
|---|---|---|
| `chat_fn` | 5 | `chatbot, log_box, session_id_state, proposed_actions_state, hitl_pending_state` |
| `handle_approve` | 6 | above 5 + `hitl_panel` |
| `handle_reject` | 6 | above 5 + `hitl_panel` |
| `clear_btn` lambda | 5 | same as `chat_fn` |
| `hitl_pending_state.change` | 2 | `action_checkbox_group, hitl_panel` |

Note: `hitl_panel` is absent from `chat_fn` outputs intentionally — visibility is driven reactively by `hitl_pending_state.change`. It is included in `handle_approve` and `handle_reject` so those handlers immediately force the panel hidden.

---

### Step 7: Make `agent/hitl.py` Async

Change only the function signature:

```python
# Before:
def run_hitl(state: OpsAgentState) -> dict:

# After:
async def run_hitl(state: OpsAgentState) -> dict:
```

No body changes. No changes to `agent/graph.py`.

---

### Step 8: Testing Checklist

Run: `python main.py --mode chat`

#### Test 1: Happy path — full approval
1. Type a fix message. Verify HITL panel appears with all actions checked by default.
2. Click "Confirm Selections". Verify panel hides and the final response appears in chat.

#### Test 2: Partial approval
1. Trigger a fix query. Uncheck at least one action. Click "Confirm Selections".
2. Verify only the checked actions appear in `executed_actions`.

#### Test 3: Reject all
1. Trigger a fix query. Click "Reject All" without modifying checkboxes.
2. Verify no actions were executed and the rejection is confirmed in the chat.

#### Test 4: Non-fix intent — no HITL trigger
1. Type a diagnose question. Verify the HITL panel never appears.

#### Test 5: State isolation across turns
1. Approve or reject a fix. Send a subsequent non-fix query.
2. Verify `session_id_state`, `proposed_actions_state`, and `hitl_pending_state` are all cleared. Panel stays hidden.

#### Test 6: Clear button resets HITL state
1. Trigger a fix, wait for the HITL panel. Click "Clear".
2. Verify the panel disappears and all state is reset.

#### Test 7: REST API async regression
1. Trigger a fix via the chatbot. Note the session ID.
2. Run `curl -X POST http://localhost:8000/hitl/approve/<session_id>`.
3. Verify the response returns without blocking delay.

#### Test 8: Shared store consistency
1. Trigger a fix. Check `GET /hitl/pending` — the session ID should appear.
2. Approve via the Gradio UI. Check `/hitl/pending` again — session should be gone.

---

## 5. File Change Summary Table

| File | Change Type | Description |
|---|---|---|
| `api/hitl_store.py` | **New file** | `HITLStore` class with `register`, `get`, `remove`, `list_pending`. Thread-safe dict wrapper. `hitl_store` singleton exported. |
| `api/hitl_api.py` | **Modified** | Remove `_pending_sessions` dict and `register_pending_session()`. Import and use `hitl_store`. Change `graph.invoke()` → `await graph.ainvoke()` in all three action endpoints. |
| `mcp_server/mcp_tools.py` | **Modified** | Remove `_hitl_pending` dict. Import and use `hitl_store` singleton. |
| `agent/hitl.py` | **Modified** | Change `def run_hitl` → `async def run_hitl`. No body changes. |
| `ui/chatbot.py` | **Modified** | Rename `chat_stream` → `chat_fn`. Add `gr.State` components. Add HITL panel with `gr.CheckboxGroup`, Confirm and Reject buttons. Add `handle_approve` and `handle_reject` handlers. Update all event wiring for new arities. Import `Command` from `langgraph.types`. |

---

## 6. Non-Goals / Out of Scope

### Database-backed session persistence
The `HITLStore` is an in-memory dict. Server restarts lose pending sessions. Production hardening requires a Redis- or Postgres-backed store and `AsyncPostgresSaver` for the graph checkpointer. Out of scope for this iteration.

### WebSocket-based real-time push
In multi-operator workflows, a WebSocket push would let the UI update reactively when another operator approves via REST API. Gradio does not natively support server-initiated push without additional infrastructure. The poll-on-submit pattern implemented here is sufficient for single-operator use.

### Per-action comment / reason fields
The `ApproveRequest` and `RejectRequest` models in `hitl_api.py` support `comment` and `reason` fields. The Gradio UI does not expose these text inputs. Adding per-action or global comment inputs is out of scope.

### Multi-tenant / multi-user session isolation
Session IDs are UUIDs with no authentication layer. Access control belongs at the API gateway layer, not within the HITL store or chatbot UI.

### Action parameter editing from the UI
The `modified_actions` path in `hitl.py` and `hitl_api.py` supports full parameter overrides. The Gradio UI only allows include/exclude selection — it does not expose a parameter editor. Adding an editable grid is out of scope.
