import json
import re
from datetime import date, datetime

from langchain_core.messages import HumanMessage
from langchain_openai import AzureChatOpenAI
from langgraph.prebuilt import create_react_agent

from agent.state import OpsAgentState, SpecialistFinding
from config import settings
from tools.campaigns import (
    get_campaign_performance,
    get_channel_breakdown,
    get_paused_campaigns,
    get_promotion_schedule,
)

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
"""

marketing_tools = [
    get_campaign_performance,
    get_channel_breakdown,
    get_paused_campaigns,
    get_promotion_schedule,
]


async def run_marketing_agent(state: OpsAgentState) -> dict:
    """Marketing specialist node."""
    sub_question = state.get("user_query", "")
    for msg in reversed(state.get("messages", [])):
        if hasattr(msg, "content") and "[MARKETING_SUBQUESTION]" in str(msg.content):
            sub_question = str(msg.content).replace("[MARKETING_SUBQUESTION]", "").strip()
            break

    today = date.today().isoformat()
    agent = create_react_agent(
        llm, marketing_tools, prompt=MARKETING_SYSTEM_PROMPT.format(today=today)
    )
    result = await agent.ainvoke({"messages": [HumanMessage(content=sub_question)]})
    final_message = result["messages"][-1].content if result.get("messages") else ""

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
        raw_tool_outputs=[{"agent_output": final_message}],
        sub_question_answered=sub_question,
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
