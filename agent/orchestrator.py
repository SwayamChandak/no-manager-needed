from datetime import datetime

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import AzureChatOpenAI
from deepeval.tracing import observe, update_current_span
from deepeval.test_case import LLMTestCase

from agent.state import OpsAgentState, OrchestratorDecision, SubQuestion
from config import settings

try:
    from eval.deepeval_setup import orchestrator_metrics
except ModuleNotFoundError:
    orchestrator_metrics = None

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

- fix: Use ONLY when the user is explicitly requesting that an action be performed or a change be made.
  Trigger words: "fix", "restock", "apply", "launch", "pause", "resolve", "correct", "update", "change", "set", "send", "create", "delete", "run".
  Example: "restock item X", "apply a 10% discount to Y", "pause campaign Z", "fix the low inventory issue".
  Do NOT use "fix" for queries that merely describe a problem or ask for information about one.

- diagnose: Use when the user wants information, analysis, or an explanation about the current state of the business — even if they mention a problem.
  This is the default for all read-only questions. Includes: "what is", "which products", "how many", "show me", "list", "identify", "why is X happening", "what's wrong with", "what are the top", "who are the customers", "tell me about".
  Example: "which products have low inventory?", "why are sales down?", "what are my top customers?", "show me underperforming campaigns".

- recall: Use ONLY when the user is asking about a PAST INCIDENT and what actions were taken to handle it — i.e. querying the memory/incident log, not live store data.
  Key signals: "last time", "what did we do when", "what was done when", "has this happened before", "how did we handle", "what steps did we take when".
  Example: "what did we do last time inventory was low?", "how did we handle the last sales drop?", "has this issue occurred before and how was it resolved?".
  Do NOT use "recall" for questions about recent or historical store data (sales figures, complaints, orders) — those are read-only data queries and must use "diagnose".
  Example of what is NOT recall: "what have the recent complaints been about?", "what were last week's sales?", "show me complaints from this month" — these are "diagnose".

- summarize: Use when the user wants a high-level overview or business health summary, not a deep diagnosis.
  Example: "summarize yesterday", "give me an executive summary", "weekly overview", "how did we do this week".

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
    return _run_orchestrator_impl(state)


@observe(metrics=orchestrator_metrics())
def _run_orchestrator_impl(state: OpsAgentState) -> dict:
    """Inner implementation wrapped by DeepEval tracing."""
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

    # Register the DeepEval test case for this span
    update_current_span(
        test_case=LLMTestCase(
            input=user_query,
            actual_output=(
                f"Intent: {decision.intent}. "
                f"Specialists: {decision.active_specialists}. "
                f"Reasoning: {decision.reasoning}"
            ),
        )
    )

    return {
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
