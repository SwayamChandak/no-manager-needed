from pydantic import BaseModel, Field
from typing import List, Optional, Any, Dict
from agent.state import RootCause, ProposedAction, ExecutedAction, PastIncident


# ── MCP Tool Inputs ────────────────────────────────────────────────────────────

class DiagnoseInput(BaseModel):
    question: str = Field(..., description="The business question to investigate.")
    session_id: str = Field(..., description="Unique session identifier for checkpointing.")


class FixInput(BaseModel):
    action_plan: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Optional override action plan. If None, the system proposes its own."
    )
    session_id: str = Field(..., description="Session ID to resume if HITL is already pending.")
    resume: bool = Field(default=False, description="Set True to resume a suspended HITL checkpoint.")
    approved: Optional[bool] = Field(default=None, description="Approval decision when resuming.")


class RecallInput(BaseModel):
    scenario_description: str = Field(..., description="Description of the current situation to match against memory.")
    top_k: int = Field(default=3, ge=1, le=10, description="Number of past incidents to retrieve.")


class SummarizeInput(BaseModel):
    date_range: str = Field(..., description="Date range to summarize, e.g. 'yesterday', '2025-01-14 to 2025-01-15'.")
    focus_areas: List[str] = Field(
        default_factory=list,
        description="Optional list of domains to focus on: 'sales', 'inventory', 'marketing', 'support'."
    )


# ── MCP Tool Outputs ───────────────────────────────────────────────────────────

class DiagnoseResult(BaseModel):
    session_id: str
    finding: str
    root_causes: List[RootCause]
    confidence: float = Field(ge=0.0, le=1.0)
    supporting_data: Dict[str, Any]
    recommended_actions: List[ProposedAction]


class FixResult(BaseModel):
    session_id: str
    status: str  # "awaiting_approval" | "executed" | "rejected"
    proposed_actions: List[ProposedAction] = Field(default_factory=list)
    actions_taken: List[ExecutedAction] = Field(default_factory=list)
    summary: str


class RecallResult(BaseModel):
    session_id: str
    incidents: List[PastIncident]
    summary: str


class SummaryResult(BaseModel):
    session_id: str
    executive_summary: str
    health_score: float = Field(ge=0.0, le=1.0, description="Overall business health score.")
    top_issues: List[str]
    recommended_actions: List[ProposedAction]
    date_range: str
