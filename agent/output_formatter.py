from datetime import datetime

from langchain_core.messages import HumanMessage
from langchain_openai import AzureChatOpenAI
from deepeval.tracing import observe, update_current_span
from deepeval.test_case import LLMTestCase

from agent.state import OpsAgentState, StructuredResponse
from config import settings
try:
    from eval.deepeval_setup import output_formatter_metrics
except ModuleNotFoundError:
    output_formatter_metrics = None

llm = AzureChatOpenAI(
    azure_endpoint=settings.azure_openai_endpoint,
    api_key=settings.azure_openai_api_key,
    azure_deployment=settings.azure_openai_deployment,
    api_version=settings.azure_openai_api_version,
    temperature=0,
)


@observe(metrics=output_formatter_metrics())
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
    hitl_rejection_reason = state.get("hitl_rejection_reason")

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

    if hitl_rejection_reason:
        context_parts.append(
            f"Human operator REJECTED all proposed actions. Reason given: \"{hitl_rejection_reason}\""
        )
    elif intent == "fix" and not executed_actions and proposed_actions:
        context_parts.append(
            "Human operator REJECTED all proposed actions. No reason was provided."
        )

    if retrieved_memories:
        lines = []
        for mem in retrieved_memories:
            lines.append(f"- Incident: '{mem.query}' (intent: {mem.intent}, recorded: {mem.timestamp})")
            if mem.root_causes:
                lines.append("  Root causes: " + "; ".join(mem.root_causes))
            if mem.actions_proposed:
                lines.append("  Actions proposed: " + "; ".join(mem.actions_proposed))
            if mem.actions_executed:
                lines.append("  Actions executed: " + "; ".join(mem.actions_executed))
            if mem.outcome_summary:
                lines.append(f"  Outcome: {mem.outcome_summary}")
        context_parts.append("Similar past incidents retrieved from memory:\n" + "\n".join(lines))

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
    elif intent == "recall":
        intent_instruction = (
            "This is a RECALL query — the user wants to understand what happened in similar past incidents. "
            "Your report must be grounded entirely in the 'Similar past incidents' data provided. "
            "For each incident: describe the situation, what caused it, what actions were taken, and the outcome. "
            "Conclude with a pattern analysis: what do these incidents have in common and what lessons apply to the current situation. "
            "Do NOT invent data not present in the incidents. Do NOT say any current actions were taken."
        )
    elif intent == "fix":
        if executed_actions:
            intent_instruction = (
                "This is a FIX query. Actions were approved by a human and executed. "
                "Report comprehensively: (1) what was found and the root causes, (2) what actions were proposed, "
                "(3) what was actually executed and the outcome for each action. "
                "If actions show status 'success', confirm they were executed successfully with specific details. "
                "If status 'failed', say those actions could not be completed and why."
            )
        else:
            intent_instruction = (
                "This is a FIX query. All proposed actions were REJECTED by the human operator. "
                "Write a comprehensive report that covers: (1) what was found and the root causes identified, "
                "(2) what actions were proposed and why they were recommended, "
                "(3) the rejection decision — include the operator's stated reason if one was provided. "
                "Do NOT say any actions were taken or executed."
            )
    else:
        intent_instruction = "Report the findings clearly and concisely."

    explanation_prompt = (
        "Write a clear business operations report in plain prose. "
        "Do NOT use any markdown formatting: no # headings, no ** bold **, no * italic *, "
        "no bullet points, no hyphens as list markers, no backticks. "
        "Use plain paragraph breaks to separate sections. "
        "Label each section with a short plain-text heading on its own line "
        "(e.g. 'What Happened', 'Root Cause Analysis', 'Next Steps'), but do not mark it up in any way.\n\n"
        "Tables are the ONLY exception. Use a plain pipe-separated table (with a header row and a "
        "separator row of dashes) when you have 2 or more rows of comparable data, such as:\n"
        "- Multiple products with sales or stock metrics\n"
        "- Multiple campaigns with performance data\n"
        "- Multiple executed or recommended actions with status or impact\n"
        "- Root causes with confidence scores\n"
        "Skip the table and write a sentence instead when there is only one row of data.\n\n"
        f"{intent_instruction}\n\n"
        "Be specific: use actual product names, quantities, campaign names, percentages, and metric values "
        "from the data. Do not use vague phrases like 'several products' or 'some items'.\n\n"
        f"{context}"
    )

    explanation_response = llm.invoke([HumanMessage(content=explanation_prompt)])
    explanation = explanation_response.content

    update_current_span(
        test_case=LLMTestCase(
            input=state.get("user_query", ""),
            actual_output=explanation,
        )
    )

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
