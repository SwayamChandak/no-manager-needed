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

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import gradio as gr
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

Intent definitions:
- diagnose: investigate, understand, or analyse an e-commerce issue
- fix: explicitly take a corrective action (restock, launch campaign, apply discount, create ticket)
- recall: ask about past incidents or similar historical events
- summarize: request a high-level business health summary

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

        from mcp_server.mcp_tools import (
            diagnose as _mcp_diagnose,
            fix as _mcp_fix,
            recall as _mcp_recall,
            summarize as _mcp_summarize,
        )

        try:
            t0 = asyncio.get_event_loop().time()

            if intent == "recall":
                yield f"data: {_json.dumps({'type': 'node_start', 'node': 'recall_node', 'input_preview': {'query': request.message[:120], 'intent': 'recall'}})}\n\n"
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

            elif intent == "diagnose":
                result = await _mcp_diagnose(question=request.message, session_id=session_id)
                duration_ms = int((asyncio.get_event_loop().time() - t0) * 1000)
                result_payload = {
                    "type": "result",
                    "session_id": result.get("session_id", session_id),
                    "finding": result.get("finding", "No finding generated."),
                    "root_causes": result.get("root_causes", []),
                    "confidence": result.get("confidence", 0.0),
                    "supporting_data": result.get("supporting_data", {}),
                    "recommended_actions": result.get("recommended_actions", []),
                    "proposed_actions": result.get("recommended_actions", []),
                    "status": "completed",
                    "duration_ms": duration_ms,
                }
                yield f"data: {_json.dumps(result_payload, default=str)}\n\n"

            elif intent == "fix":
                result = await _mcp_fix(query=request.message, session_id=session_id)
                duration_ms = int((asyncio.get_event_loop().time() - t0) * 1000)
                status = result.get("status", "unknown")
                if status == "awaiting_approval":
                    proposed = result.get("proposed_actions", [])
                    actions_payload = [
                        a.model_dump() if hasattr(a, "model_dump") else a
                        for a in proposed
                    ]
                    yield f"data: {_json.dumps({'type': 'interrupt', 'proposed_actions': actions_payload, 'status': 'awaiting_approval', 'session_id': session_id, 'duration_ms': duration_ms})}\n\n"
                else:
                    result_payload = {
                        "type": "result",
                        "session_id": result.get("session_id", session_id),
                        "finding": result.get("summary", ""),
                        "root_causes": [],
                        "confidence": 0.0,
                        "supporting_data": {},
                        "recommended_actions": result.get("proposed_actions", []),
                        "proposed_actions": result.get("proposed_actions", []),
                        "actions_taken": result.get("actions_taken", []),
                        "status": status,
                        "duration_ms": duration_ms,
                    }
                    yield f"data: {_json.dumps(result_payload, default=str)}\n\n"

            elif intent == "summarize":
                result = await _mcp_summarize(date_range=request.message)
                duration_ms = int((asyncio.get_event_loop().time() - t0) * 1000)
                result_payload = {
                    "type": "result",
                    "session_id": result.get("session_id", session_id),
                    "finding": result.get("executive_summary", "No summary generated."),
                    "root_causes": [],
                    "confidence": result.get("health_score", 0.0),
                    "supporting_data": {"top_issues": result.get("top_issues", [])},
                    "recommended_actions": result.get("recommended_actions", []),
                    "proposed_actions": result.get("recommended_actions", []),
                    "status": "completed",
                    "duration_ms": duration_ms,
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
