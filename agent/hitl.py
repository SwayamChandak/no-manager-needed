from datetime import datetime

from langgraph.types import interrupt

from agent.state import OpsAgentState, ProposedAction


def run_hitl(state: OpsAgentState) -> dict:
    """
    HITL checkpoint node.
    - For 'fix' intent: suspends graph via interrupt(), waits for human approval.
    - For all other intents: passes through without interrupting.

    On resume after approval, interrupt() returns the approval payload.
    On resume after rejection, approved_actions will be empty.
    """
    intent = state.get("intent", "diagnose")

    if intent != "fix":
        return {}

    proposed_actions = state.get("proposed_actions", [])
    actions_payload = [a.model_dump() for a in proposed_actions]

    approval_response = interrupt(
        {
            "message": "Human approval required before executing actions.",
            "proposed_actions": actions_payload,
            "session_id": state.get("session_id", ""),
        }
    )

    approved = (
        approval_response.get("approved", False)
        if isinstance(approval_response, dict)
        else False
    )
    modified_actions = (
        approval_response.get("modified_actions")
        if isinstance(approval_response, dict)
        else None
    )

    if approved:
        if modified_actions:
            approved_list = [ProposedAction(**a) for a in modified_actions]
        else:
            approved_list = proposed_actions
    else:
        approved_list = []

    return {
        "approved_actions": approved_list,
        "tool_call_log": [
            {
                "node": "hitl",
                "approved": approved,
                "actions_approved_count": len(approved_list),
                "timestamp": datetime.utcnow().isoformat(),
            }
        ],
    }
