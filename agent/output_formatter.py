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

    context_parts = [f"User query: {state.get('user_query', '')}"]

    if root_causes:
        context_parts.append(
            "Root causes:\n"
            + "\n".join(
                f"- {rc.description} (confidence: {rc.confidence:.0%})"
                for rc in root_causes
            )
        )

    if executed_actions:
        context_parts.append(
            "Actions executed:\n"
            + "\n".join(f"- {ea.action_type}: {ea.status}" for ea in executed_actions)
        )

    if reflection_notes and any("[MAX RETRIES" in n for n in reflection_notes):
        context_parts.append(
            "Note: Analysis completed with limited confidence due to data gaps."
        )

    context = "\n\n".join(context_parts)

    explanation_prompt = (
        "Write a clear, concise explanation (2-4 sentences) for a business user based on "
        "this operations analysis.\n"
        "Be direct. State what happened, why, and what was done or recommended.\n\n"
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
