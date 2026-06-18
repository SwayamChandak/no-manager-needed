import json
import re
from datetime import date, datetime

from langchain_core.messages import HumanMessage
from langchain_openai import AzureChatOpenAI
from langgraph.prebuilt import create_react_agent
from deepeval.tracing import observe, update_current_span
from deepeval.test_case import LLMTestCase

from agent.state import OpsAgentState, SpecialistFinding
from config import settings
try:
    from eval.deepeval_setup import marketing_metrics
except ModuleNotFoundError:
    marketing_metrics = None
from tools.registry import get_tools_for_agent

llm = AzureChatOpenAI(
    azure_endpoint=settings.azure_openai_endpoint,
    api_key=settings.azure_openai_api_key,
    azure_deployment=settings.azure_openai_deployment,
    api_version=settings.azure_openai_api_version,
    temperature=0,
)

MARKETING_SYSTEM_PROMPT = """You are the Marketing & Campaigns specialist agent for an e-commerce operations system.
You have tools to check campaign performance, channel breakdowns, paused campaigns, and promotion schedules.
Default date: {today}.

Tool notes:
- get_campaign_performance: Returns spend, impressions, clicks, conversions, revenue, and ROAS per campaign. Pass a date for that day's metrics; omit date for all-time aggregated totals per campaign.
- get_channel_breakdown: Returns aggregate spend, revenue, and ROAS grouped by marketing channel. Pass a date for that day's channel split; omit date for all-time channel totals.
- get_paused_campaigns: Returns paused campaigns with the timestamp and reason. Pass a date to filter to campaigns paused on that specific day; omit date to return all campaigns currently in 'paused' status.
- get_promotion_schedule: Returns all currently active or upcoming promotions with their discount %, affected product IDs, and start/end times. No date parameter.
- get_campaign_status_breakdown: Returns a count, total budget, and total spend grouped by campaign status (active, paused, completed, cancelled). Use this to understand the overall health and distribution of campaigns. No parameters.

When no specific date is mentioned in the query, call tools WITHOUT a date argument to get the broadest available view.
"""


@observe(metrics=marketing_metrics())
async def run_marketing_agent(state: OpsAgentState) -> dict:
    """Marketing specialist node."""
    sub_question = state.get("user_query", "")
    for msg in reversed(state.get("messages", [])):
        if hasattr(msg, "content") and "[MARKETING_SUBQUESTION]" in str(msg.content):
            sub_question = str(msg.content).replace("[MARKETING_SUBQUESTION]", "").strip()
            break

    today = date.today().isoformat()
    agent = create_react_agent(
        llm, get_tools_for_agent("marketing"), prompt=MARKETING_SYSTEM_PROMPT.format(today=today)
    )
    result = await agent.ainvoke({"messages": [HumanMessage(content=sub_question)]})
    final_message = result["messages"][-1].content if result.get("messages") else ""

    # Extract actual tool outputs from ToolMessages in the ReAct agent's message history
    from langchain_core.messages import ToolMessage as _ToolMessage
    tool_outputs = []
    for msg in result.get("messages", []):
        if isinstance(msg, _ToolMessage):
            try:
                import json as _json
                tool_outputs.append(_json.loads(msg.content))
            except (ValueError, TypeError):
                tool_outputs.append({"raw": str(msg.content)[:500]})
    if not tool_outputs:
        tool_outputs = [{"agent_output": final_message}]

    summary_response = await llm.ainvoke(
        [
            HumanMessage(
                content=f"""Extract from this marketing investigation:
1. Key signals (3-5 short strings)
2. Confidence 0.0-1.0

Result: {final_message}

Return JSON: {{"signals": ["...", "..."], "confidence": 0.0}}"""
            )
        ]
    )
    json_match = re.search(r"\{.*\}", summary_response.content, re.DOTALL)
    parsed = (
        json.loads(json_match.group())
        if json_match
        else {"signals": [final_message[:200]], "confidence": 0.5}
    )

    finding = SpecialistFinding(
        domain="marketing",
        signals=parsed.get("signals", []),
        confidence=parsed.get("confidence", 0.5),
        raw_tool_outputs=tool_outputs,
        sub_question_answered=sub_question,
    )

    update_current_span(
        test_case=LLMTestCase(
            input=sub_question,
            actual_output=final_message,
            retrieval_context=[
                json.dumps(o, default=str) for o in tool_outputs[:6]
            ] if tool_outputs else None,
        )
    )

    return {
        "marketing_findings": finding,
        "tool_call_log": [
            {
                "node": "marketing_agent",
                "sub_question": sub_question,
                "timestamp": datetime.utcnow().isoformat(),
            }
        ],
    }
