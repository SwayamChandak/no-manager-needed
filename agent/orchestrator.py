from datetime import datetime

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import AzureChatOpenAI

from agent.state import OpsAgentState, OrchestratorDecision, SubQuestion
from config import settings

llm = AzureChatOpenAI(
    azure_endpoint=settings.azure_openai_endpoint,
    api_key=settings.azure_openai_api_key,
    azure_deployment=settings.azure_openai_deployment,
    api_version=settings.azure_openai_api_version,
    temperature=0,
)

INTENT_ROUTING_PROMPT = """You are the orchestrator of an e-commerce AI ops system.
Your job is to parse the user's question and decide:
1. The intent: one of "diagnose", "fix", "recall", "summarize"
2. Which specialist agents are relevant: any subset of ["sales", "inventory", "marketing", "support"]
3. A specific sub-question for each relevant specialist to investigate

Intent definitions:
- diagnose: user wants to understand the current state OR why something happened. Use this for ANY query that asks "what", "which", "how many", "show me", "list", "name", "identify", or "why". This is the default for all read-only investigative questions.
- fix: user EXPLICITLY wants the system to take a corrective action using keywords like "fix", "restock", "apply discount", "pause", "launch a campaign", "resolve", "correct it". Do NOT use this for queries that just ask for information about problems.
- recall: user is asking about past incidents ("what happened last time", "has this occurred before")
- summarize: user wants a high-level business health summary ("summarize yesterday", "executive summary")

Rules for specialist routing:
- "diagnose" or "fix" with cross-domain question → all 4 specialists
- Pure sales question → sales only
- Pure stock/inventory question → inventory only
- Pure campaign/marketing question → marketing only
- Pure support/complaints question → support only
- If in doubt, route to all 4

Return a JSON object matching this schema exactly:
{
  "intent": "<diagnose|fix|recall|summarize>",
  "active_specialists": ["<specialist>", ...],
  "sub_questions": [
    {"specialist": "<specialist>", "question": "<specific sub-question for this specialist to investigate>"}
  ],
  "reasoning": "<brief explanation of routing decision>"
}
"""

REFLECTION_REENTRY_PROMPT = """You are the orchestrator of an e-commerce AI ops system.
A reflection check found gaps in the previous analysis. Here are the reflection notes:
{reflection_notes}

The original user query was: {user_query}

Your job is to decide which specialists need to be re-queried with refined sub-questions to fill these gaps.
Return the same JSON schema as before but only include specialists that need to do additional investigation.

{{
  "intent": "<same as original>",
  "active_specialists": ["<only specialists that need follow-up>"],
  "sub_questions": [
    {{"specialist": "<specialist>", "question": "<refined sub-question addressing the gap>"}}
  ],
  "reasoning": "<why these specific follow-ups are needed>"
}}
"""


def run_orchestrator(state: OpsAgentState) -> dict:
    """
    Orchestrator node function.
    On first entry: parses intent, routes to specialists.
    On re-entry from reflection loop: sends targeted follow-up sub-questions.
    """
    retry_count = state.get("retry_count", 0)
    reflection_notes = state.get("reflection_notes", [])
    user_query = state.get("user_query", "")

    if retry_count > 0 and reflection_notes:
        prompt = REFLECTION_REENTRY_PROMPT.format(
            reflection_notes="\n".join(reflection_notes),
            user_query=user_query,
        )
        messages = [SystemMessage(content=prompt)]
    else:
        messages = [
            SystemMessage(content=INTENT_ROUTING_PROMPT),
            HumanMessage(content=user_query),
        ]

    structured_llm = llm.with_structured_output(OrchestratorDecision)
    decision: OrchestratorDecision = structured_llm.invoke(messages)

    specialist_messages = []
    for sq in decision.sub_questions:
        specialist_messages.append(
            HumanMessage(
                content=f"[{sq.specialist.upper()}_SUBQUESTION] {sq.question}",
                name="orchestrator",
            )
        )

    return {
        "intent": decision.intent,
        "active_specialists": decision.active_specialists,
        "retry_count": retry_count + 1 if retry_count > 0 else 0,
        "messages": specialist_messages,
        "tool_call_log": [
            {
                "node": "orchestrator",
                "decision": decision.model_dump(),
                "timestamp": datetime.utcnow().isoformat(),
            }
        ],
    }
