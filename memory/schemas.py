from pydantic import BaseModel, Field
from typing import List
import uuid
from datetime import datetime


class IncidentRecord(BaseModel):
    """
    An episodic memory record written to Qdrant after every completed run.
    The embedding_text field is what gets embedded and stored as the vector.
    """
    incident_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    query: str
    intent: str  # "diagnose" | "fix" | "recall" | "summarize"
    root_causes: List[str]
    actions_proposed: List[str]
    actions_approved: List[str]
    actions_executed: List[str]
    outcome_summary: str
    embedding_text: str  # concatenation of query + root_causes + actions; used for vector search

    @classmethod
    def build_embedding_text(
        cls,
        query: str,
        root_causes: List[str],
        actions_proposed: List[str],
    ) -> str:
        """Build the text that will be embedded for semantic retrieval."""
        parts = [
            f"Query: {query}",
            "Root causes: " + "; ".join(root_causes),
            "Actions: " + "; ".join(actions_proposed),
        ]
        return " | ".join(parts)
