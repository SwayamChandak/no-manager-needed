import json
from datetime import datetime

from agent.state import ExecutedAction, OpsAgentState
from tools.actions import current_session_id
from tools.registry import get_tools_for_agent

# action_type strings that differ from their tool function name
_ACTION_ALIASES: dict[str, str] = {
    "restock": "restock_product",
    "create_ticket": "create_support_ticket",
}


def _build_action_tool_map() -> dict:
    """Build action_type → LangChain tool mapping dynamically from the registry."""
    tools = get_tools_for_agent("action_executor")
    tool_map = {t.name: t for t in tools}
    # Add short aliases so action_types like "restock" resolve to "restock_product"
    for alias, tool_name in _ACTION_ALIASES.items():
        if tool_name in tool_map:
            tool_map[alias] = tool_map[tool_name]
    return tool_map


async def run_action_executor(state: OpsAgentState) -> dict:
    """
    Action executor node — calls the appropriate tool for each approved action.
    Only reached after HITL approval (approved_actions is non-empty).
    """
    approved_actions = state.get("approved_actions", [])
    session_id = state.get("session_id", "")
    executed = []
    action_tool_map = _build_action_tool_map()

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
            tool_fn = action_tool_map.get(action_type)

            # Normalize stale parameter keys to match current tool signatures
            if action_type == "pause_campaign":
                if "campaign_id" in params and "campaign_name" not in params:
                    params["campaign_name"] = params.pop("campaign_id")
            elif action_type == "relaunch_campaign":
                if "campaign_id" in params and "campaign_name" not in params:
                    params["campaign_name"] = params.pop("campaign_id")
            elif action_type == "launch_campaign":
                if "product_ids" in params and "product_names" not in params:
                    params["product_names"] = params.pop("product_ids")

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
