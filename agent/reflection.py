from datetime import datetime

from agent.state import OpsAgentState
from config import settings


def run_reflection(state: OpsAgentState) -> dict:
    """
    Reflection node — checks quality of aggregation before proceeding.
    Sets reflection_passed=True if quality is acceptable, False otherwise.
    Writes specific reflection_notes describing what is missing.
    """
    notes = []
    threshold = settings.reflection_confidence_threshold
    intent = state.get("intent", "diagnose")
    root_causes = state.get("root_causes", [])
    proposed_actions = state.get("proposed_actions", [])
    retry_count = state.get("retry_count", 0)

    # Check 1: Are there any root causes at all (for diagnose/fix)?
    if intent in ("diagnose", "fix") and not root_causes:
        notes.append(
            "No root causes identified. Specialists may not have retrieved sufficient data."
        )

    # Check 2: Are all root causes below confidence threshold?
    if root_causes:
        low_confidence = [rc for rc in root_causes if rc.confidence < threshold]
        if len(low_confidence) == len(root_causes):
            notes.append(
                f"All {len(root_causes)} root cause(s) are below confidence threshold {threshold}. "
                "Request more targeted data from specialists."
            )

    # Check 3: Fix intent requires at least one proposed action
    if intent == "fix" and not proposed_actions:
        notes.append(
            "Intent is 'fix' but no actions were proposed. "
            "Aggregator needs more concrete findings."
        )

    # Check 4: Any specialist returned empty signals when they were invoked?
    for domain in ["sales", "inventory", "marketing", "support"]:
        active = state.get("active_specialists", [])
        if domain in active:
            finding = state.get(f"{domain}_findings")
            if finding is None or not finding.signals:
                notes.append(
                    f"{domain.capitalize()} specialist was invoked but returned no signals. "
                    "Re-query with a more specific sub-question."
                )

    # On max retries, always pass to avoid infinite loop — but flag low confidence
    if retry_count >= settings.max_reflection_retries:
        if notes:
            notes.append("[MAX RETRIES REACHED] Proceeding with low-confidence output.")
        passed = True
    else:
        passed = len(notes) == 0

    return {
        "reflection_passed": passed,
        "reflection_notes": notes,
        "tool_call_log": [
            {
                "node": "reflection",
                "passed": passed,
                "notes_count": len(notes),
                "retry_count": retry_count,
                "timestamp": datetime.utcnow().isoformat(),
            }
        ],
    }
