"""
api/hitl_api.py — HITL approval API.

Endpoints for human operators to approve, reject, or modify proposed actions.
The graph is suspended at the hitl_node interrupt() until one of these is called.
Uses Command(resume=...) from langgraph.types to resume the interrupted graph.
"""

from typing import Optional, List, Dict, Any
from datetime import datetime

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from langgraph.types import Command

from agent.graph import graph
from api.hitl_store import hitl_store

hitl_app = FastAPI(
    title="E-Commerce Ops Agent — HITL API",
    description="Human-in-the-loop approval endpoints for the ops agent.",
    version="1.0.0",
)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class ApproveRequest(BaseModel):
    modified_actions: Optional[List[Dict[str, Any]]] = None
    comment: Optional[str] = None


class RejectRequest(BaseModel):
    reason: Optional[str] = None


class HITLStatusResponse(BaseModel):
    session_id: str
    status: str
    proposed_actions: List[Dict[str, Any]]
    retrieved_at: str


class ActionResponse(BaseModel):
    session_id: str
    status: str
    message: str
    timestamp: str


def _graph_config(session_id: str) -> dict:
    return {"configurable": {"thread_id": session_id}}


def _get_pending_state(session_id: str) -> dict:
    """Read proposed actions from the live graph checkpoint."""
    try:
        snapshot = graph.get_state(_graph_config(session_id))
        if snapshot is None:
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
        proposed = snapshot.values.get("proposed_actions", [])
        return {
            "proposed_actions": [
                a.model_dump() if hasattr(a, "model_dump") else a for a in proposed
            ]
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' not found or not suspended: {exc}",
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@hitl_app.get("/pending", summary="List all sessions awaiting approval")
async def list_pending() -> List[str]:
    """Returns session IDs of all graphs currently suspended at the HITL checkpoint."""
    pending = []
    for sid in hitl_store.list_pending():
        try:
            snapshot = graph.get_state(_graph_config(sid))
            # Include if graph is still suspended (has next nodes) or just registered
            if snapshot is None or snapshot.next:
                pending.append(sid)
        except Exception:
            # If we can't read the state, keep it in the list (conservative)
            pending.append(sid)
    return pending


@hitl_app.get("/pending/{session_id}", summary="Get proposed actions for a session")
async def get_pending(session_id: str) -> HITLStatusResponse:
    """Returns the proposed actions waiting for approval for a specific session."""
    state_data = _get_pending_state(session_id)
    return HITLStatusResponse(
        session_id=session_id,
        status="awaiting_approval",
        proposed_actions=state_data["proposed_actions"],
        retrieved_at=datetime.utcnow().isoformat(),
    )


@hitl_app.post("/approve/{session_id}", summary="Approve proposed actions")
async def approve(
    session_id: str,
    request: ApproveRequest = ApproveRequest(),
) -> ActionResponse:
    """
    Approves the proposed actions for a session. The suspended graph resumes
    and proceeds to the action_executor node.

    Optionally supply modified_actions to approve with modifications.
    """
    config = _graph_config(session_id)
    approval_payload = {
        "approved": True,
        "modified_actions": request.modified_actions,
        "comment": request.comment,
    }

    try:
        await graph.ainvoke(Command(resume=approval_payload), config=config)
        hitl_store.remove(session_id)
        return ActionResponse(
            session_id=session_id,
            status="executed",
            message="Actions approved and executed successfully.",
            timestamp=datetime.utcnow().isoformat(),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to resume graph: {exc}")


@hitl_app.post("/reject/{session_id}", summary="Reject proposed actions")
async def reject(
    session_id: str,
    request: RejectRequest = RejectRequest(),
) -> ActionResponse:
    """
    Rejects the proposed actions. The graph resumes but routes to output_formatter
    without executing anything. No production state is mutated.
    """
    config = _graph_config(session_id)
    rejection_payload = {
        "approved": False,
        "modified_actions": None,
        "comment": request.reason,
    }

    try:
        await graph.ainvoke(Command(resume=rejection_payload), config=config)
        hitl_store.remove(session_id)
        return ActionResponse(
            session_id=session_id,
            status="rejected",
            message=f"Actions rejected. Reason: {request.reason or 'No reason provided.'}",
            timestamp=datetime.utcnow().isoformat(),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to resume graph: {exc}")


@hitl_app.post("/modify/{session_id}", summary="Approve with modified actions")
async def modify_and_approve(
    session_id: str,
    request: ApproveRequest,
) -> ActionResponse:
    """
    Approves with a modified action plan. Supply modified_actions to override
    what the system proposed. Graph resumes and executes the modified plan.
    """
    if not request.modified_actions:
        raise HTTPException(
            status_code=400,
            detail="modified_actions is required for this endpoint.",
        )

    config = _graph_config(session_id)
    approval_payload = {
        "approved": True,
        "modified_actions": request.modified_actions,
        "comment": request.comment,
    }

    try:
        await graph.ainvoke(Command(resume=approval_payload), config=config)
        hitl_store.remove(session_id)
        return ActionResponse(
            session_id=session_id,
            status="executed",
            message=(
                f"Modified action plan approved and executed "
                f"({len(request.modified_actions)} actions)."
            ),
            timestamp=datetime.utcnow().isoformat(),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to resume graph: {exc}")


@hitl_app.get("/health", summary="Health check")
async def health() -> dict:
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}
