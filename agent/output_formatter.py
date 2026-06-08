from datetime import datetime

from langchain_core.messages import HumanMessage
from langchain_openai import AzureChatOpenAI

from agent.state import OpsAgentState, StructuredResponse
from config import settings

llm = AzureChatOpenAI(
    azure_endpoint=settings.azure_openai_endpoint,
    api_key=settings.azure_openai_api_key,
    azure_deployment=settings.azure_openai_deployment,
    api_version=settings.azure_openai_api_version,
    temperature=0,
)


def run_output_formatter(state: OpsAgentState) -> dict:
    """
    Output formatter node — assembles the final StructuredResponse.
    Uses LLM to write a coherent natural-language explanation from all state data.
    """
    root_causes = state.get("root_causes", [])
    proposed_actions = state.get("proposed_actions", [])
    executed_actions = state.get("executed_actions", [])
    retrieved_memories = state.get("retrieved_memories", [])
    intent = state.get("intent", "diagnose")
    reflection_notes = state.get("reflection_notes", [])

    import json as _json

    context_parts = [f"User query: {state.get('user_query', '')}"]

    # Include specialist findings with actual tool data (product names, quantities, etc.)
    for domain in ("sales", "inventory", "marketing", "support"):
        finding = state.get(f"{domain}_findings")
        if finding is None:
            continue
        signals = getattr(finding, "signals", [])
        raw_outputs = getattr(finding, "raw_tool_outputs", [])
        parts = []
        if signals:
            parts.append("Signals: " + "; ".join(signals))
        for i, raw in enumerate(raw_outputs):
            if isinstance(raw, dict):
                raw_str = _json.dumps(raw, default=str)
                if len(raw_str) > 1500:
                    raw_str = raw_str[:1500] + "... [truncated]"
                parts.append(f"Tool data: {raw_str}")
        if parts:
            context_parts.append(f"{domain.capitalize()} findings:\n" + "\n".join(parts))

    if root_causes:
        context_parts.append(
            "Root causes:\n"
            + "\n".join(
                f"- {rc.description} (confidence: {rc.confidence:.0%})"
                for rc in root_causes
            )
        )

    if proposed_actions:
        lines = []
        for pa in proposed_actions:
            atype = getattr(pa, "action_type", "action")
            params = getattr(pa, "parameters", "{}")
            justification = getattr(pa, "justification", "")
            impact = getattr(pa, "estimated_impact", "")
            lines.append(f"- {atype}: {params}")
            if justification:
                lines.append(f"  Reason: {justification}")
            if impact:
                lines.append(f"  Impact: {impact}")
        # Label differs by intent: diagnose → recommendations only, fix → pending approval
        if intent == "fix":
            action_label = "Actions pending HITL approval (NOT yet executed):"
        else:
            action_label = "Recommended actions (NOT executed — analysis only):"
        context_parts.append(f"{action_label}\n" + "\n".join(lines))

    if executed_actions:
        lines = []
        for ea in executed_actions:
            atype = getattr(ea, "action_type", "action")
            status = getattr(ea, "status", "?")
            params = getattr(ea, "parameters", {})
            api_resp = getattr(ea, "api_response", {}) or {}
            param_str = _json.dumps(params, default=str) if params else ""
            resp_str = _json.dumps(api_resp, default=str) if api_resp else ""
            lines.append(f"- {atype} ({param_str}): {status}")
            if resp_str and len(resp_str) < 300:
                lines.append(f"  API response: {resp_str}")
        context_parts.append("Actions executed:\n" + "\n".join(lines))

    if reflection_notes and any("[MAX RETRIES" in n for n in reflection_notes):
        context_parts.append(
            "Note: Analysis completed with limited confidence due to data gaps."
        )

    context = "\n\n".join(context_parts)

    if intent == "diagnose":
        intent_instruction = (
            "This is a DIAGNOSTIC query — the user asked for information only. "
            "NO actions have been executed. Do NOT say actions were 'initiated', 'submitted', or 'taken'. "
            "If there are recommended actions in the context, present them as suggestions or next steps only."
        )
    elif intent == "fix":
        if executed_actions:
            intent_instruction = (
                "This is a FIX query. Actions were approved by a human and executed. "
                "Report what was found AND what was done. "
                "If actions show status 'success', confirm they were executed successfully. "
                "If status 'failed', say those actions could not be completed."
            )
        else:
            intent_instruction = (
                "This is a FIX query but no actions were executed (they may have been rejected). "
                "Report only what was found. Do NOT say actions were taken."
            )
    else:
        intent_instruction = "Report the findings clearly and concisely."

    explanation_prompt = (
        "Write a clear, concise explanation (3-5 sentences) for a business user based on "
        "this operations analysis.\n"
        f"{intent_instruction}\n"
        "Be specific: use actual product names, quantities, campaign names, or metric values "
        "from the data provided — do NOT use vague phrases like 'several products' or 'some items'.\n\n"
        f"{context}"
    )

    explanation_response = llm.invoke([HumanMessage(content=explanation_prompt)])
    explanation = explanation_response.content

    confidence = (
        sum(rc.confidence for rc in root_causes) / len(root_causes)
        if root_causes
        else 0.0
    )

    response = StructuredResponse(
        session_id=state.get("session_id", ""),
        intent=intent,
        explanation=explanation,
        root_causes=root_causes,
        recommended_actions=proposed_actions,
        executed_actions=executed_actions,
        retrieved_memories=retrieved_memories,
        confidence=round(confidence, 2),
    )

    return {
        "final_response": response,
        "tool_call_log": [
            {
                "node": "output_formatter",
                "intent": intent,
                "confidence": confidence,
                "timestamp": datetime.utcnow().isoformat(),
            }
        ],
    }
