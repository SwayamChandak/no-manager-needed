import operator
from typing import TypedDict, Optional, List, Dict, Any, Annotated
from pydantic import BaseModel, ConfigDict, Field
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from datetime import datetime


class SpecialistFinding(BaseModel):
    """Output from a single specialist agent."""
    domain: str  # "sales" | "inventory" | "marketing" | "support"
    signals: List[str]  # list of key observations as strings
    confidence: float = Field(ge=0.0, le=1.0)
    raw_tool_outputs: List[Dict[str, Any]] = Field(default_factory=list)
    sub_question_answered: str = ""


class RootCause(BaseModel):
    """A single identified root cause with confidence and evidence."""
    model_config = ConfigDict(extra="forbid")
    description: str
    confidence: float = Field(ge=0.0, le=1.0)
    supporting_domains: List[str]
    evidence: List[str]


class ProposedAction(BaseModel):
    """An action proposed by the aggregator for human approval."""
    model_config = ConfigDict(extra="forbid")
    action_type: str  # "restock" | "apply_discount" | "pause_campaign" | "create_ticket"
    parameters: str  # JSON-encoded dict, e.g. '{"product_id": "SKU-123", "quantity": 50}'
    justification: str
    estimated_impact: str


class ExecutedAction(BaseModel):
    """An action that has been executed after HITL approval."""
    action_type: str
    parameters: Dict[str, Any]
    status: str  # "success" | "failed"
    timestamp: str
    api_response: Optional[Dict[str, Any]] = None


class SubQuestion(BaseModel):
    """A sub-question routed to a specific specialist."""
    model_config = ConfigDict(extra="forbid")
    specialist: str  # "sales" | "inventory" | "marketing" | "support"
    question: str


class OrchestratorDecision(BaseModel):
    """Structured LLM output from the orchestrator's routing step."""
    model_config = ConfigDict(extra="forbid")
    intent: str  # "diagnose" | "fix" | "recall" | "summarize"
    active_specialists: List[str]  # subset of ["sales", "inventory", "marketing", "support"]
    sub_questions: List[SubQuestion]
    reasoning: str


class PairCorrelation(BaseModel):
    """Causal correlation between two specialist domains."""
    model_config = ConfigDict(extra="forbid")
    linked: bool
    explanation: str


class CorrelationMatrix(BaseModel):
    """Pairwise correlation analysis across all domain pairs."""
    model_config = ConfigDict(extra="forbid")
    sales_inventory: PairCorrelation
    sales_marketing: PairCorrelation
    sales_support: PairCorrelation
    inventory_marketing: PairCorrelation
    inventory_support: PairCorrelation
    marketing_support: PairCorrelation


class AggregatorOutput(BaseModel):
    """Output from the aggregator node."""
    model_config = ConfigDict(extra="forbid")
    correlation_matrix: CorrelationMatrix
    root_causes: List[RootCause]
    proposed_actions: List[ProposedAction]
    summary: str


class PastIncident(BaseModel):
    """A past incident retrieved from long-term memory."""
    incident_id: str
    timestamp: str
    query: str
    intent: str
    root_causes: List[str]
    actions_proposed: List[str]
    actions_executed: List[str]
    outcome_summary: str


class StructuredResponse(BaseModel):
    """Final user-facing structured response from the output formatter."""
    session_id: str
    intent: str
    explanation: str
    root_causes: List[RootCause] = Field(default_factory=list)
    recommended_actions: List[ProposedAction] = Field(default_factory=list)
    executed_actions: List[ExecutedAction] = Field(default_factory=list)
    retrieved_memories: List[PastIncident] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class OpsAgentState(TypedDict):
    """LangGraph graph state — the single source of truth throughout a session."""
    # Input
    session_id: str
    user_query: str
    intent: str  # "diagnose" | "fix" | "recall" | "summarize"

    # Routing
    active_specialists: List[str]
    retry_count: int

    # Specialist outputs
    sales_findings: Optional[SpecialistFinding]
    inventory_findings: Optional[SpecialistFinding]
    marketing_findings: Optional[SpecialistFinding]
    support_findings: Optional[SpecialistFinding]

    # Aggregation
    root_causes: List[RootCause]
    correlation_matrix: Dict[str, Any]

    # Reflection
    reflection_notes: List[str]
    reflection_passed: bool

    # Actions
    proposed_actions: List[ProposedAction]
    approved_actions: List[ProposedAction]
    executed_actions: List[ExecutedAction]
    hitl_rejection_reason: Optional[str]

    # Memory
    retrieved_memories: List[PastIncident]

    # Output
    final_response: Optional[StructuredResponse]

    # Metadata
    messages: Annotated[List[BaseMessage], add_messages]
    tool_call_log: Annotated[List[Dict[str, Any]], operator.add]
    timestamp: str
