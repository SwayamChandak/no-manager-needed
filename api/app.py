"""
api/app.py — Combined App Server FastAPI application (Process 2).

Mounts:
  /ui   → Gradio chatbot (ui/chatbot.py)
  /hitl → HITL approval endpoints (api/hitl_api.py)
  POST /chat → MCP proxy to Process 1 (MCP Server)

Run via `python -m api`.
"""

import json as _json
import asyncio
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import gradio as gr
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import AzureChatOpenAI as _AzureChatOpenAI

from agent.graph import graph
from api.hitl_api import hitl_app
from config import settings

app = FastAPI(
    title="E-Commerce Ops Agent — App Server",
    description="Chat UI, HITL approval, and MCP proxy.",
    version="1.0.0",
)

# Mount HITL sub-application
app.mount("/hitl", hitl_app)

# ---------------------------------------------------------------------------
# Chat proxy — forwards requests to the MCP Server
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str
    session_id: str
    intent: str = "diagnose"  # diagnose | fix | recall | summarize


@app.post("/chat")
async def chat(request: ChatRequest) -> dict:
    """
    Proxy a chat message to the MCP Server.
    The MCP Server runs the LangGraph graph and returns a structured result.
    """
    try:
        from fastmcp import Client as MCPClient

        async with MCPClient(settings.mcp_server_url) as client:
            if request.intent == "fix":
                tool_params = {"query": request.message, "session_id": request.session_id}
            elif request.intent == "recall":
                tool_params = {"scenario_description": request.message}
            else:  # diagnose, summarize
                tool_params = {"question": request.message, "session_id": request.session_id}

            result = await client.call_tool(request.intent, tool_params)
        import json as _json

        # Handle CallToolResult (modern fastmcp) and legacy list response
        # 1. If result has .data (already parsed dict), return it directly
        if hasattr(result, "data") and isinstance(result.data, dict):
            return result.data
        # 2. If result has .content list (CallToolResult without .data), extract first text
        if hasattr(result, "content") and result.content:
            text = result.content[0].text if hasattr(result.content[0], "text") else str(result.content[0])
            try:
                return _json.loads(text)
            except (ValueError, TypeError):
                return {"result": text}
        # 3. Legacy: plain list
        if isinstance(result, list) and result:
            content = result[0]
            if hasattr(content, "text"):
                try:
                    return _json.loads(content.text)
                except (ValueError, TypeError):
                    return {"result": content.text}
        return {"result": str(result)}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"MCP Server error: {e}")


# ---------------------------------------------------------------------------
# Helpers for /chat/stream
# ---------------------------------------------------------------------------

_intent_llm = _AzureChatOpenAI(
    azure_endpoint=settings.azure_openai_endpoint,
    api_key=settings.azure_openai_api_key,
    azure_deployment=settings.azure_openai_deployment,
    api_version=settings.azure_openai_api_version,
    temperature=0,
)

_INTENT_PROMPT = """You are an intent classifier for an e-commerce AI ops agent.
Classify the user's message into exactly one of these four intents and reply with ONLY that single word:

- diagnose: user wants to investigate, understand, or analyse (e.g. "why did sales drop", "show revenue", "which products are low on stock")
- fix: user EXPLICITLY wants the system to take a corrective action (e.g. "launch a campaign", "start an email campaign", "restock", "apply a discount", "pause promotion", "create a ticket", "resolve", "execute", "run a campaign", "set up a promotion")
- recall: user asks about past incidents (e.g. "has this happened before", "find similar incidents")
- summarize: user wants a high-level business health summary (e.g. "summarize today", "executive summary")

Reply with exactly one word: diagnose, fix, recall, or summarize."""


def _classify_intent(message: str) -> str:
    """Use LLM to classify intent. Falls back to 'diagnose' on any error."""
    try:
        resp = _intent_llm.invoke([
            SystemMessage(content=_INTENT_PROMPT),
            HumanMessage(content=message),
        ])
        intent = resp.content.strip().lower()
        if intent in ("diagnose", "fix", "recall", "summarize"):
            return intent
    except Exception:
        pass
    return "diagnose"


def _build_stream_state(message: str, session_id: str, intent: str) -> dict:
    from agent.state import OpsAgentState  # noqa: F401 — import kept local
    return {
        "session_id": session_id,
        "user_query": message,
        "intent": intent,
        "active_specialists": ["sales", "inventory", "marketing", "support"],
        "retry_count": 0,
        "sales_findings": None,
        "inventory_findings": None,
        "marketing_findings": None,
        "support_findings": None,
        "root_causes": [],
        "correlation_matrix": {},
        "reflection_notes": [],
        "reflection_passed": False,
        "proposed_actions": [],
        "approved_actions": [],
        "executed_actions": [],
        "retrieved_memories": [],
        "final_response": None,
        "messages": [HumanMessage(content=message)],
        "tool_call_log": [],
        "timestamp": datetime.utcnow().isoformat(),
    }


# ---------------------------------------------------------------------------
# SSE streaming endpoint
# ---------------------------------------------------------------------------

@app.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """
    Stream LangGraph execution events as SSE (Server-Sent Events).
    Each event is a JSON line: data: {...}\n\n

    Event types emitted:
      - intent_classified: {type, intent}
      - node_start: {type, node, input_preview}
      - node_end: {type, node, duration_ms}
      - tool_start: {type, node, tool, input_preview}
      - tool_end: {type, node, tool, output_preview, duration_ms}
      - llm_start: {type, node}
      - llm_end: {type, node, tokens}
      - interrupt: {type, proposed_actions}
      - result: {type, ...full result dict...}
      - error: {type, message}
    """
    intent = request.intent if request.intent != "auto" else _classify_intent(request.message)
    session_id = request.session_id
    config = {"configurable": {"thread_id": session_id}}

    _GRAPH_NODES = frozenset({
        "orchestrator_node", "sales_node", "inventory_node",
        "marketing_node", "support_node", "aggregator_node",
        "reflection_node", "hitl_node", "action_executor_node",
        "memory_writer_node", "recall_node", "output_formatter_node",
    })

    async def event_generator():
        yield f"data: {_json.dumps({'type': 'intent_classified', 'intent': intent})}\n\n"

        node_start_times: dict = {}

        # ── Recall: bypass graph, call MCP recall tool directly ────────────
        if intent == "recall":
            from mcp_server.mcp_tools import recall as _mcp_recall
            try:
                yield f"data: {_json.dumps({'type': 'node_start', 'node': 'recall_node', 'input_preview': {'query': request.message[:120], 'intent': 'recall'}})}\n\n"
                t0 = asyncio.get_event_loop().time()
                result = await _mcp_recall(scenario_description=request.message)
                duration_ms = int((asyncio.get_event_loop().time() - t0) * 1000)
                yield f"data: {_json.dumps({'type': 'node_end', 'node': 'recall_node', 'duration_ms': duration_ms})}\n\n"
                result_payload = {
                    "type": "result",
                    "session_id": result.get("session_id", session_id),
                    "finding": result.get("summary", "No incidents found."),
                    "incidents": result.get("incidents", []),
                    "root_causes": [],
                    "confidence": 0.0,
                    "supporting_data": {},
                    "recommended_actions": [],
                    "proposed_actions": [],
                    "status": "completed",
                }
                yield f"data: {_json.dumps(result_payload, default=str)}\n\n"
            except Exception as exc:
                import traceback
                yield f"data: {_json.dumps({'type': 'error', 'message': str(exc), 'detail': traceback.format_exc()[:500]})}\n\n"
            return

        initial_state = _build_stream_state(request.message, session_id, intent)

        try:
            async for event in graph.astream_events(initial_state, config=config, version="v2"):
                kind = event.get("event", "")
                name = event.get("name", "")
                data = event.get("data", {})

                # ── Node start ──────────────────────────────────────────────
                if kind == "on_chain_start" and name in _GRAPH_NODES:
                    node_start_times[name] = asyncio.get_event_loop().time()
                    inp = data.get("input", {})
                    preview = {}
                    if isinstance(inp, dict):
                        if "user_query" in inp:
                            preview["query"] = inp["user_query"][:120]
                        if "intent" in inp:
                            preview["intent"] = inp["intent"]
                    yield f"data: {_json.dumps({'type': 'node_start', 'node': name, 'input_preview': preview})}\n\n"

                # ── Node end ────────────────────────────────────────────────
                elif kind == "on_chain_end" and name in _GRAPH_NODES:
                    start = node_start_times.pop(name, asyncio.get_event_loop().time())
                    duration_ms = int((asyncio.get_event_loop().time() - start) * 1000)
                    yield f"data: {_json.dumps({'type': 'node_end', 'node': name, 'duration_ms': duration_ms})}\n\n"

                # ── Tool start ──────────────────────────────────────────────
                elif kind == "on_tool_start":
                    inp = data.get("input", {})
                    inp_str = _json.dumps(inp, default=str)[:200] if isinstance(inp, dict) else str(inp)[:200]
                    tags = event.get("tags", [])
                    parent_node = next((t for t in tags if t.endswith("_node")), "unknown")
                    yield f"data: {_json.dumps({'type': 'tool_start', 'node': parent_node, 'tool': name, 'input_preview': inp_str})}\n\n"

                # ── Tool end ────────────────────────────────────────────────
                elif kind == "on_tool_end":
                    out = data.get("output", "")
                    out_str = str(out)[:300]
                    tags = event.get("tags", [])
                    parent_node = next((t for t in tags if t.endswith("_node")), "unknown")
                    yield f"data: {_json.dumps({'type': 'tool_end', 'node': parent_node, 'tool': name, 'output_preview': out_str})}\n\n"

                # ── LLM start ───────────────────────────────────────────────
                elif kind == "on_chat_model_start":
                    tags = event.get("tags", [])
                    parent_node = next((t for t in tags if t.endswith("_node")), "unknown")
                    yield f"data: {_json.dumps({'type': 'llm_start', 'node': parent_node})}\n\n"

                # ── LLM end ─────────────────────────────────────────────────
                elif kind == "on_chat_model_end":
                    tags = event.get("tags", [])
                    parent_node = next((t for t in tags if t.endswith("_node")), "unknown")
                    usage = {}
                    try:
                        usage_meta = data.get("output", {})
                        if hasattr(usage_meta, "usage_metadata"):
                            um = usage_meta.usage_metadata
                            usage = {
                                "input": um.get("input_tokens", 0),
                                "output": um.get("output_tokens", 0),
                            }
                    except Exception:
                        pass
                    yield f"data: {_json.dumps({'type': 'llm_end', 'node': parent_node, 'tokens': usage})}\n\n"

            # ── After stream: read final state ────────────────────────────
            snapshot = graph.get_state(config)
            state_vals = snapshot.values if snapshot else {}

            if snapshot and snapshot.next:
                proposed = state_vals.get("proposed_actions", [])
                actions_payload = [
                    a.model_dump() if hasattr(a, "model_dump") else a
                    for a in proposed
                ]
                yield f"data: {_json.dumps({'type': 'interrupt', 'proposed_actions': actions_payload, 'status': 'awaiting_approval', 'session_id': session_id})}\n\n"
            else:
                final_response = state_vals.get("final_response")
                root_causes = state_vals.get("root_causes", [])
                confidence = (
                    sum(rc.confidence for rc in root_causes) / len(root_causes)
                    if root_causes else 0.0
                )
                result_payload = {
                    "type": "result",
                    "session_id": session_id,
                    "finding": final_response.explanation if final_response else "No finding generated.",
                    "root_causes": [
                        rc.model_dump() if hasattr(rc, "model_dump") else rc
                        for rc in root_causes
                    ],
                    "confidence": round(confidence, 2),
                    "supporting_data": state_vals.get("correlation_matrix", {}),
                    "recommended_actions": [
                        a.model_dump() if hasattr(a, "model_dump") else a
                        for a in state_vals.get("proposed_actions", [])
                    ],
                    "proposed_actions": [
                        a.model_dump() if hasattr(a, "model_dump") else a
                        for a in state_vals.get("proposed_actions", [])
                    ],
                    "status": "completed",
                }
                yield f"data: {_json.dumps(result_payload, default=str)}\n\n"

        except Exception as exc:
            import traceback
            yield f"data: {_json.dumps({'type': 'error', 'message': str(exc), 'detail': traceback.format_exc()[:500]})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Mount Gradio UI
# ---------------------------------------------------------------------------

from ui.chatbot import demo as gradio_demo  # noqa: E402

app = gr.mount_gradio_app(app, gradio_demo, path="/ui")
