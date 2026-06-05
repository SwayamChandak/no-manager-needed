from typing import List
from agent.state import OpsAgentState, PastIncident, SpecialistFinding


def get_active_findings(state: OpsAgentState) -> dict[str, SpecialistFinding]:
    """Return a dict of domain -> finding for all non-None specialist findings."""
    result = {}
    for domain in ["sales", "inventory", "marketing", "support"]:
        finding = state.get(f"{domain}_findings")
        if finding is not None:
            result[domain] = finding
    return result


def get_low_confidence_domains(state: OpsAgentState, threshold: float) -> List[str]:
    """Return list of domains whose specialist findings are below the confidence threshold."""
    low = []
    for domain, finding in get_active_findings(state).items():
        if finding.confidence < threshold:
            low.append(domain)
    return low


def inject_memories_into_state(
    memories: List[PastIncident],
    state: OpsAgentState,
) -> dict:
    """Return a state update dict that sets retrieved_memories."""
    return {"retrieved_memories": memories}


def build_memory_context_string(memories: List[PastIncident]) -> str:
    """Format retrieved memories as a readable string for LLM prompts."""
    if not memories:
        return "No relevant past incidents found."
    parts = []
    for i, mem in enumerate(memories, 1):
        parts.append(
            f"Past Incident #{i} ({mem.timestamp[:10]}):\n"
            f"  Query: {mem.query}\n"
            f"  Root Causes: {'; '.join(mem.root_causes)}\n"
            f"  Actions Taken: {'; '.join(mem.actions_executed)}\n"
            f"  Outcome: {mem.outcome_summary}"
        )
    return "\n\n".join(parts)
