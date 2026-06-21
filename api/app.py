"""
api/app.py — Combined App Server FastAPI application (Process 2).

Mounts:
  /ui   → React SPA (ui-react/build/)
  /hitl → HITL approval endpoints (api/hitl_api.py)
  POST /chat → MCP proxy to Process 1 (MCP Server)

Run via `python -m api`.
"""

import json as _json
import asyncio
import os

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import AzureChatOpenAI as _AzureChatOpenAI

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
# Helpers for /chat/stream
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str
    session_id: str
    intent: str = "auto"  # auto | diagnose | fix | recall | summarize


_intent_llm = _AzureChatOpenAI(
    azure_endpoint=settings.azure_openai_endpoint,
    api_key=settings.azure_openai_api_key,
    azure_deployment=settings.azure_openai_deployment,
    api_version=settings.azure_openai_api_version,
    temperature=0,
)

_INTENT_PROMPT = """You are the query gatekeeper for an AI-powered e-commerce operations agent.
Your job is to decide whether the user's message is within scope AND classify its intent.

IN-SCOPE topics:
- Sales performance (revenue, orders, conversion rates, product sales trends)
- Inventory management (stock levels, stockouts, restocking, warehouse ops)
- Marketing (campaigns, promotions, discounts, ad spend, channel performance)
- Customer support (complaints, tickets, refunds, satisfaction scores)
- Cross-domain operations analysis and business health summaries
- Past incident retrieval and pattern recognition from the above domains

OUT-OF-SCOPE topics (reject these):
- General knowledge, science, history, geography, coding, recipes, etc.
- Personal advice, jokes, creative writing
- Topics unrelated to the store's sales / inventory / marketing / support operations

If IN-SCOPE, reply with exactly one word from: diagnose, fix, recall, summarize

INTENT DEFINITIONS (read carefully — pick the FIRST that applies in this order):

 1. fix — The user explicitly asks you to TAKE a corrective action NOW.
    Trigger words: restock, launch, apply, create, set, enable, refund, cancel, send, pause, stop, disable, update, adjust, modify, change, flag.
    Examples:
    - "Restock the blue widgets."
    - "Launch a discount campaign for shoes."
    - "Create a support ticket for this customer."
    - "Pause all underperforming marketing campaigns."
    - "Flag low-stock products as discontinued."

2. summarize — The user wants a high-level overview of overall business health.
   Trigger phrases: "how's the business", "give me an overview", "overall status", "summary of everything".
   Examples:
   - "Give me a summary of how the store is doing."
   - "What's the overall health of operations this week?"

3. recall — The user asks about a SPECIFIC, ALREADY-RESOLVED PAST incident or wants to
   find historical precedents/patterns to compare against. This is about looking up the
   archive of closed events, NOT about current data.
   Key signal: references a prior known event, "last time", "have we seen this before",
   "similar incidents", "in the past when X happened".
   Examples:
   - "Have we had a stockout like this before?"
   - "What happened last time we ran a flash sale?"
   - "Find past incidents similar to this conversion drop."

4. diagnose — The DEFAULT. The user wants to investigate, understand, analyze, or get
   the CURRENT state of an ongoing e-commerce situation. Use this for any question that
   asks WHAT, WHY, or HOW about present/recent operational data, even if it uses words
   like "recent" or "lately".
   Examples:
   - "What have the recent complaints been about?"   -> diagnose
   - "How are our marketing campaigns performing?"    -> diagnose
   - "Why did sales drop this week?"                  -> diagnose
   - "What's our current stock level on widgets?"     -> diagnose

DISAMBIGUATION RULES:
- "recent", "lately", "this week", "currently" describe CURRENT operations -> diagnose, NOT recall.
- recall ONLY applies when the user explicitly points to a closed/historical incident or
  asks for comparison with past events ("before", "last time", "previously", "similar past cases").
- If a message both asks to understand AND to act, prefer fix only if an action verb is present;
  otherwise diagnose.
- When in doubt between diagnose and recall, choose diagnose.

If OUT-OF-SCOPE, reply with exactly: REJECTED: <one concise sentence explaining the assistant only handles e-commerce ops topics such as sales, inventory, marketing, and customer support>

Examples of REJECTED replies:
  REJECTED: I can only help with e-commerce operations topics such as sales trends, inventory, marketing campaigns, and customer support.
  REJECTED: That question is outside my scope — I specialise in sales, inventory, marketing, and support operations for this store.

IMPORTANT: Reply with ONLY the single intent word OR the REJECTED line. Nothing else."""


def _classify_intent(message: str) -> tuple[str, str | None]:
    """Use LLM to classify intent with guardrails.

    Returns (intent, rejection_message).
    If in-scope: ("diagnose"|"fix"|"recall"|"summarize", None)
    If out-of-scope: ("rejected", user-facing rejection message)
    Falls back to ("diagnose", None) on any LLM error.
    """
    try:
        resp = _intent_llm.invoke([
            SystemMessage(content=_INTENT_PROMPT),
            HumanMessage(content=message),
        ])
        raw = resp.content.strip()
        lower = raw.lower()
        if lower in ("diagnose", "fix", "recall", "summarize"):
            return lower, None
        if lower.startswith("rejected:"):
            rejection_msg = raw[len("rejected:"):].strip()
            return "rejected", rejection_msg or "I can only help with e-commerce operations topics: sales, inventory, marketing, and customer support."
    except Exception:
        pass
    return "diagnose", None



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
      - node_start: {type, node}
      - node_end: {type, node}
      - token: {type, node, content}  ← live LLM token chunks
      - tool_start: {type, node, tool, input_preview}
      - tool_end: {type, node, tool}
      - interrupt: {type, proposed_actions}
      - result: {type, ...full result dict...}
      - error: {type, message}
    """
    intent = request.intent if request.intent != "auto" else None
    rejection_message: str | None = None
    if intent is None:
        intent, rejection_message = _classify_intent(request.message)
    session_id = request.session_id

    async def event_generator():
        if intent == "rejected":
            yield f"data: {_json.dumps({'type': 'off_topic', 'message': rejection_message})}\n\n"
            return

        yield f"data: {_json.dumps({'type': 'intent_classified', 'intent': intent})}\n\n"

        from mcp_server.mcp_tools import stream_graph_execution

        try:
            async for etype, edata in stream_graph_execution(request.message, session_id, intent):
                if etype == "node_start":
                    yield f"data: {_json.dumps({'type': 'node_start', 'node': edata})}\n\n"
                elif etype == "node_end":
                    yield f"data: {_json.dumps({'type': 'node_end', 'node': edata})}\n\n"
                elif etype == "token":
                    yield f"data: {_json.dumps({'type': 'token', 'node': edata['node'], 'content': edata['content']})}\n\n"
                elif etype == "tool_start":
                    yield f"data: {_json.dumps({'type': 'tool_start', 'node': edata.get('node', ''), 'tool': edata.get('tool', ''), 'input_preview': edata.get('input_preview', '')})}\n\n"
                elif etype == "tool_end":
                    yield f"data: {_json.dumps({'type': 'tool_end', 'node': edata.get('node', ''), 'tool': edata.get('tool', '')})}\n\n"
                elif etype == "interrupt":
                    yield f"data: {_json.dumps({'type': 'interrupt', 'proposed_actions': edata.get('proposed_actions', []), 'status': 'awaiting_approval', 'session_id': edata.get('session_id', session_id)})}\n\n"
                elif etype == "result":
                    final_state = edata
                    fr = final_state.get("final_response")
                    root_causes = final_state.get("root_causes", [])
                    proposed_actions = final_state.get("proposed_actions", [])
                    active_specialists = final_state.get("active_specialists", [])

                    if intent == "recall":
                        result_payload = {
                            "type": "result",
                            "session_id": final_state.get("session_id", session_id),
                            "finding": fr.explanation if fr else "No incidents found.",
                            "incidents": [m.model_dump() if hasattr(m, "model_dump") else m for m in final_state.get("retrieved_memories", [])],
                            "root_causes": [],
                            "confidence": 0.0,
                            "recommended_actions": [],
                            "proposed_actions": [],
                            "active_specialists": [],
                            "status": "completed",
                        }
                    elif intent == "diagnose":
                        confidence = (
                            sum(rc.confidence for rc in root_causes) / len(root_causes)
                            if root_causes else 0.0
                        )
                        result_payload = {
                            "type": "result",
                            "session_id": final_state.get("session_id", session_id),
                            "finding": fr.explanation if fr else "No finding generated.",
                            "root_causes": [rc.model_dump() if hasattr(rc, "model_dump") else rc for rc in root_causes],
                            "confidence": round(confidence, 2),
                            "supporting_data": final_state.get("correlation_matrix", {}),
                            "recommended_actions": proposed_actions,
                            "proposed_actions": proposed_actions,
                            "active_specialists": active_specialists,
                            "status": "completed",
                        }
                    elif intent == "fix":
                        executed_actions = final_state.get("executed_actions", [])
                        result_payload = {
                            "type": "result",
                            "session_id": final_state.get("session_id", session_id),
                            "finding": fr.explanation if fr else "",
                            "root_causes": [rc.model_dump() if hasattr(rc, "model_dump") else rc for rc in root_causes],
                            "confidence": 0.0,
                            "recommended_actions": proposed_actions,
                            "proposed_actions": proposed_actions,
                            "actions_taken": [ea.model_dump() if hasattr(ea, "model_dump") else ea for ea in executed_actions],
                            "active_specialists": active_specialists,
                            "status": "completed",
                        }
                    elif intent == "summarize":
                        result_payload = {
                            "type": "result",
                            "session_id": final_state.get("session_id", session_id),
                            "finding": fr.explanation if fr else "No summary generated.",
                            "root_causes": [],
                            "confidence": 0.0,
                            "supporting_data": {"top_issues": [rc.description for rc in root_causes[:5]]},
                            "recommended_actions": proposed_actions,
                            "proposed_actions": proposed_actions,
                            "active_specialists": active_specialists,
                            "status": "completed",
                        }
                    else:
                        result_payload = {
                            "type": "result",
                            "session_id": final_state.get("session_id", session_id),
                            "finding": fr.explanation if fr else "Done.",
                            "root_causes": [],
                            "confidence": 0.0,
                            "active_specialists": active_specialists,
                            "status": "completed",
                        }
                    yield f"data: {_json.dumps(result_payload, default=str)}\n\n"
                elif etype == "error":
                    yield f"data: {_json.dumps({'type': 'error', 'message': edata.get('message', 'Unknown error')})}\n\n"

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
# Serve React UI build
# ---------------------------------------------------------------------------

_react_build = os.path.join(os.path.dirname(__file__), "..", "ui-react", "build")
if os.path.isdir(_react_build):
    app.mount("/ui", StaticFiles(directory=_react_build, html=True), name="ui")
