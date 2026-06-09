import json
from datetime import datetime

from agent.state import ExecutedAction, OpsAgentState
from tools.actions import (
    apply_discount,
    create_support_ticket,
    launch_campaign,
    pause_campaign,
    relaunch_campaign,
    restock_product,
    current_session_id,
)

ACTION_TOOL_MAP = {
    "restock": restock_product,
    "apply_discount": apply_discount,
    "pause_campaign": pause_campaign,
    "relaunch_campaign": relaunch_campaign,
    "launch_campaign": launch_campaign,
    "create_ticket": create_support_ticket,
}


async def run_action_executor(state: OpsAgentState) -> dict:
    """
    Action executor node — calls the appropriate tool for each approved action.
    Only reached after HITL approval (approved_actions is non-empty).
    """
    approved_actions = state.get("approved_actions", [])
    session_id = state.get("session_id", "")
    executed = []

    # Inject session_id into the ContextVar so action tools can record it
    token = current_session_id.set(session_id)
    try:
        for action in approved_actions:
            try:
                params = (
                    json.loads(action.parameters)
                    if isinstance(action.parameters, str)
                    else action.parameters
                )
            except (json.JSONDecodeError, TypeError):
                params = {}

            action_type = action.action_type
            tool_fn = ACTION_TOOL_MAP.get(action_type)

            if tool_fn is None:
                executed.append(
                    ExecutedAction(
                        action_type=action_type,
                        parameters=params,
                        status="failed",
                        timestamp=datetime.utcnow().isoformat(),
                        api_response={"error": f"No tool registered for action_type '{action_type}'"},
                    )
                )
                continue

            try:
                result = await tool_fn.ainvoke(params)
                executed.append(
                    ExecutedAction(
                        action_type=action_type,
                        parameters=params,
                        status="success",
                        timestamp=datetime.utcnow().isoformat(),
                        api_response=result if isinstance(result, dict) else {"result": str(result)},
                    )
                )
            except Exception as e:
                executed.append(
                    ExecutedAction(
                        action_type=action_type,
                        parameters=params,
                        status="failed",
                        timestamp=datetime.utcnow().isoformat(),
                        api_response={"error": str(e)},
                    )
                )
    finally:
        current_session_id.reset(token)

    return {
        "executed_actions": executed,
        "tool_call_log": [
            {
                "node": "action_executor",
                "actions_attempted": len(approved_actions),
                "actions_succeeded": sum(1 for e in executed if e.status == "success"),
                "timestamp": datetime.utcnow().isoformat(),
            }
        ],
    }
