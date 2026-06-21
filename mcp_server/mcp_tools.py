"""
mcp_server/mcp_tools.py — MCP tool implementations.

Renamed from tools.py to avoid shadowing the project-level tools/ package when
fastmcp dev inspector adds mcp_server/ to sys.path.

Each function is registered as an MCP tool via mcp.tool()(fn) in server.py.
Tools are thin wrappers: they build initial graph state, invoke the graph,
and map the result to an MCP output schema.
No LLM calls, no business logic — all intelligence lives in the LangGraph graph.
"""

import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from agent.graph import graph
from agent.state import OpsAgentState, PastIncident
from memory.long_term import long_term_memory
from mcp_server.schemas import (
    DiagnoseResult,
    FixResult,
    RecallResult,
    SummaryResult,
)
from api.hitl_store import hitl_store


# ---------------------------------------------------------------------------
# Streaming graph execution — emits tokens + events in real-time
# ---------------------------------------------------------------------------

async def stream_graph_execution(query: str, session_id: str, intent_hint: str = "diagnose"):
    """
    Async generator that yields (event_type, data) tuples during graph execution.

    Event types:
        ("node_start", node_name: str)
        ("node_end", node_name: str)
        ("token", {"node": str, "content": str})
        ("tool_start", {"node": str, "tool": str, "input_preview": str})
        ("tool_end", {"node": str, "tool": str})
        ("interrupt", {"proposed_actions": [...], "session_id": str})
        ("result", final_state: dict)
        ("error", {"message": str})
    """
    initial_state = _build_initial_state(query, session_id, intent_hint)
    config = _graph_config(session_id)

    active_node: str | None = None
    saw_interrupt = False

    try:
        async for event in graph.astream_events(initial_state, config, version="v2"):
            kind = event["event"]
            metadata = event.get("metadata") or {}
            node = metadata.get("langgraph_node", "") or ""

            if kind == "on_chain_start":
                if node and node != active_node:
                    if active_node:
                        yield ("node_end", active_node)
                    active_node = node
                    yield ("node_start", node)

            elif kind == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                content = ""
                if hasattr(chunk, "content"):
                    content = chunk.content or ""
                elif isinstance(chunk, str):
                    content = chunk
                if content:
                    yield ("token", {"node": active_node or node or "unknown", "content": content})

            elif kind == "on_tool_start":
                tool_name = event.get("name", "")
                tool_input = event.get("data", {}).get("input", "")
                yield ("tool_start", {"node": active_node or node, "tool": tool_name, "input_preview": str(tool_input)[:200]})

            elif kind == "on_tool_end":
                tool_name = event.get("name", "")
                yield ("tool_end", {"node": active_node or node, "tool": tool_name})

    except Exception as exc:
        snapshot = graph.get_state(config)
        if snapshot and snapshot.next:
            saw_interrupt = True
            proposed = snapshot.values.get("proposed_actions", [])
            yield ("interrupt", {
                "proposed_actions": [a.model_dump() if hasattr(a, "model_dump") else a for a in proposed],
                "session_id": session_id,
            })
        else:
            yield ("error", {"message": str(exc)})
            return

    if active_node:
        yield ("node_end", active_node)

    if not saw_interrupt:
        snapshot = graph.get_state(config)
        if snapshot and snapshot.next:
            proposed = snapshot.values.get("proposed_actions", [])
            yield ("interrupt", {
                "proposed_actions": [a.model_dump() if hasattr(a, "model_dump") else a for a in proposed],
                "session_id": session_id,
            })
        elif snapshot:
            yield ("result", dict(snapshot.values))


def _build_initial_state(query: str, session_id: str, intent_hint: str = "diagnose") -> OpsAgentState:
    """Build a minimal initial OpsAgentState for a fresh graph invocation."""
    return {
        "session_id": session_id,
        "user_query": query,
        "intent": intent_hint,
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
        "hitl_rejection_reason": None,
        "retrieved_memories": [],
        "final_response": None,
        "messages": [HumanMessage(content=query)],
        "tool_call_log": [],
        "timestamp": datetime.utcnow().isoformat(),
    }


def _graph_config(session_id: str) -> dict:
    return {"configurable": {"thread_id": session_id}}


# ---------------------------------------------------------------------------
# Tool: diagnose
# ---------------------------------------------------------------------------
async def diagnose(question: str, session_id: str) -> dict:
    """
    Investigate a business question across all domains.
    Runs the full multi-agent graph: orchestrator → specialists → aggregator → reflection → output.
    Does NOT execute any actions. Safe to call freely.

    Args:
        question: The business question, e.g. 'Why did sales drop yesterday?'
        session_id: Unique session ID for checkpointing (use uuid4 string).

    Returns a structured finding with root causes and recommended actions.
    """
    initial_state = _build_initial_state(question, session_id, "diagnose")
    result = await graph.ainvoke(initial_state, config=_graph_config(session_id))
    print("diagnose called")
    # Safety net: if graph suspended at HITL (should not happen for diagnose intent),
    # return a clear message instead of "No finding generated."
    diag_snapshot = graph.get_state(_graph_config(session_id))
    if diag_snapshot and diag_snapshot.next:
        return DiagnoseResult(
            session_id=session_id,
            finding="This query requires corrective actions. Please rephrase using fix intent (e.g., 'launch a campaign', 'restock', 'fix').",
            root_causes=result.get("root_causes", []),
            confidence=0.0,
            supporting_data={},
            recommended_actions=result.get("proposed_actions", []),
            active_specialists=result.get("active_specialists", []),
        ).model_dump()

    final_response = result.get("final_response")
    root_causes = result.get("root_causes", [])

    confidence = (
        sum(rc.confidence for rc in root_causes) / len(root_causes)
        if root_causes else 0.0
    )

    supporting_data = result.get("correlation_matrix", {})

    return DiagnoseResult(
        session_id=session_id,
        finding=final_response.explanation if final_response else "No finding generated.",
        root_causes=root_causes,
        confidence=round(confidence, 2),
        supporting_data=supporting_data,
        recommended_actions=result.get("proposed_actions", []),
        active_specialists=result.get("active_specialists", []),
    ).model_dump()


# ---------------------------------------------------------------------------
# Tool: fix
# ---------------------------------------------------------------------------
async def fix(
    query: str = "Fix the identified issue and propose corrective actions.",
    session_id: str = "",
    action_plan: Optional[List[Dict[str, Any]]] = None,
    resume: bool = False,
    approved: Optional[bool] = None,
) -> dict:
    """
    Propose and execute corrective actions. Requires human approval before execution.

    First call: runs the graph until the HITL checkpoint, returns status='awaiting_approval'
    with the proposed actions listed.

    Second call (after human decision): set resume=True and approved=True/False.
    On approval, the graph resumes and executes the actions.
    On rejection, returns status='rejected' with no mutations.

    Args:
        query: The business issue to investigate and fix. e.g. 'Restock product P001 which is out of stock.'
        session_id: Session ID (must match the first call's session_id for resume).
        action_plan: Optional override action list. If None, the system proposes its own.
        resume: Set True when resuming after HITL approval/rejection.
        approved: True to approve and execute, False to reject. Required when resume=True.

    Returns FixResult with status: 'awaiting_approval' | 'executed' | 'rejected'.
    """
    session_id = session_id or str(uuid.uuid4())
    config = _graph_config(session_id)
    print("fix called")
    if resume:
        # Resume the suspended graph with the human decision
        approval_payload = {
            "approved": approved if approved is not None else False,
            "modified_actions": action_plan,  # None if no modifications
        }
        result = await graph.ainvoke(Command(resume=approval_payload), config=config)

        final_response = result.get("final_response")
        executed = result.get("executed_actions", [])
        approved_actions = result.get("approved_actions", [])

        status = "executed" if (approved and executed) else "rejected"

        hitl_store.remove(session_id)

        return FixResult(
            session_id=session_id,
            status=status,
            proposed_actions=approved_actions,
            actions_taken=executed,
            summary=final_response.explanation if final_response else f"Actions {status}.",
        ).model_dump()

    # Fresh run — graph will suspend at hitl_node for fix intent
    initial_state = _build_initial_state(query, session_id, "fix")

    try:
        result = await graph.ainvoke(initial_state, config=config)

        # LangGraph >= 0.2: detect interrupt via graph.get_state().next (non-empty = suspended)
        snapshot = graph.get_state(config)
        if snapshot and snapshot.next:
            proposed = result.get("proposed_actions", [])
            hitl_store.register(session_id, [a.model_dump() if hasattr(a, "model_dump") else a for a in proposed])
            return FixResult(
                session_id=session_id,
                status="awaiting_approval",
                proposed_actions=proposed,
                actions_taken=[],
                summary=(
                    f"The system has identified {len(proposed)} action(s) requiring your approval. "
                    "Call fix() again with resume=True and approved=True/False to proceed."
                ),
                active_specialists=result.get("active_specialists", []),
            ).model_dump()

        # Graph ran to completion without interrupting
        final_response = result.get("final_response")
        executed = result.get("executed_actions", [])
        return FixResult(
            session_id=session_id,
            status="executed",
            proposed_actions=result.get("approved_actions", []),
            actions_taken=executed,
            summary=final_response.explanation if final_response else "Actions executed.",
            active_specialists=result.get("active_specialists", []),
        ).model_dump()

    except Exception as exc:
        # Graph hit interrupt() — surfaces as GraphInterrupt in some LangGraph versions.
        # Verify the graph actually suspended before treating this as HITL.
        snapshot = graph.get_state(config)
        if not (snapshot and snapshot.next):
            # Not a HITL interrupt — re-raise as a real error
            raise
        proposed = snapshot.values.get("proposed_actions", [])
        hitl_store.register(session_id, [a.model_dump() for a in proposed])

        return FixResult(
            session_id=session_id,
            status="awaiting_approval",
            proposed_actions=proposed,
            actions_taken=[],
            summary=(
                f"The system has identified {len(proposed)} action(s) requiring your approval. "
                "Call fix() again with resume=True and approved=True/False to proceed."
            ),
            active_specialists=snapshot.values.get("active_specialists", []),
        ).model_dump()


# ---------------------------------------------------------------------------
# Tool: recall
# ---------------------------------------------------------------------------
async def recall(scenario_description: str, top_k: int = 3) -> dict:
    """
    Retrieve similar past incidents from long-term memory and produce a
    detailed narrative report via the output formatter.

    Invokes the LangGraph graph with intent=recall so results flow through
    recall_node (Qdrant search) → output_formatter_node (LLM report).

    Args:
        scenario_description: Description of the current situation to find similar past incidents for.
        top_k: Number of past incidents to retrieve (1-10, default 3).

    Returns a RecallResult with a comprehensive narrative summary and the raw incidents list.
    """
    print("recall called")
    session_id = str(uuid.uuid4())
    config = _graph_config(session_id)

    initial_state = _build_initial_state(scenario_description, session_id, "recall")
    # top_k is not a state field; pre-fetch incidents here so the caller's top_k is honoured,
    # then let the graph also run recall_node (which uses its own default top_k=5).
    # We use the graph result as the authoritative output.
    result = await graph.ainvoke(initial_state, config=config)

    final_response = result.get("final_response")
    incidents = result.get("retrieved_memories", [])

    if final_response and final_response.explanation:
        summary = final_response.explanation
    elif incidents:
        summary = (
            f"Found {len(incidents)} similar past incident(s). "
            f"Most relevant: '{incidents[0].query}' — {incidents[0].outcome_summary}"
        )
    else:
        summary = "No similar past incidents found in memory."

    return RecallResult(
        session_id=session_id,
        incidents=incidents,
        summary=summary,
        active_specialists=[],
    ).model_dump()


# ---------------------------------------------------------------------------
# Tool: summarize
# ---------------------------------------------------------------------------
async def summarize(date_range: str, focus_areas: Optional[List[str]] = None) -> dict:
    """
    Generate an executive business health summary for a date range.
    Invokes the full specialist graph in summarize mode.

    Args:
        date_range: Date range to summarize, e.g. 'yesterday', '2025-01-14 to 2025-01-15'.
        focus_areas: Optional list of domains to focus on: 'sales', 'inventory', 'marketing', 'support'.
                     If empty or None, all four domains are included.

    Returns an executive summary with health score, top issues, and recommended actions.
    """
    session_id = str(uuid.uuid4())
    focus = [
        f for f in (focus_areas or ["sales", "inventory", "marketing", "support"])
        if f in {"sales", "inventory", "marketing", "support"}
    ] or ["sales", "inventory", "marketing", "support"]

    query = f"Summarize business health for {date_range}. Focus areas: {', '.join(focus)}."
    initial_state = _build_initial_state(query, session_id, "summarize")
    initial_state["active_specialists"] = focus

    result = await graph.ainvoke(initial_state, config=_graph_config(session_id))

    final_response = result.get("final_response")
    root_causes = result.get("root_causes", [])

    # Health score: inverse of average root cause confidence (higher concern = lower health)
    avg_concern = (
        sum(rc.confidence for rc in root_causes) / len(root_causes)
        if root_causes else 0.0
    )
    health_score = round(max(0.0, 1.0 - avg_concern), 2)

    top_issues = [rc.description for rc in root_causes[:5]]

    return SummaryResult(
        session_id=session_id,
        executive_summary=final_response.explanation if final_response else "No summary generated.",
        health_score=health_score,
        top_issues=top_issues,
        recommended_actions=result.get("proposed_actions", []),
        date_range=date_range,
        active_specialists=result.get("active_specialists", focus),
    ).model_dump()
