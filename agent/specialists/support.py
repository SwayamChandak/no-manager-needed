import json
import re
from datetime import date, datetime

from langchain_core.messages import HumanMessage
from langchain_openai import AzureChatOpenAI
from langgraph.prebuilt import create_react_agent

from agent.state import OpsAgentState, SpecialistFinding
from config import settings
from tools.crm import (
    get_common_issues,
    get_complaint_volume,
    get_review_sentiment,
)

llm = AzureChatOpenAI(
    azure_endpoint=settings.azure_openai_endpoint,
    api_key=settings.azure_openai_api_key,
    azure_deployment=settings.azure_openai_deployment,
    api_version=settings.azure_openai_api_version,
    temperature=0,
)

SUPPORT_SYSTEM_PROMPT = """You are the Customer Support & Experience specialist agent for an e-commerce operations system.
You have tools to check complaint volume, refund rates, review sentiment, and common customer issues.
Default date: {today}.
"""

support_tools = [
    get_complaint_volume,
    get_review_sentiment,
    get_common_issues,
]


async def run_support_agent(state: OpsAgentState) -> dict:
    """Support specialist node."""
    sub_question = state.get("user_query", "")
    for msg in reversed(state.get("messages", [])):
        if hasattr(msg, "content") and "[SUPPORT_SUBQUESTION]" in str(msg.content):
            sub_question = str(msg.content).replace("[SUPPORT_SUBQUESTION]", "").strip()
            break

    today = date.today().isoformat()
    agent = create_react_agent(
        llm, support_tools, prompt=SUPPORT_SYSTEM_PROMPT.format(today=today)
    )
    result = await agent.ainvoke({"messages": [HumanMessage(content=sub_question)]})
    final_message = result["messages"][-1].content if result.get("messages") else ""

    summary_response = await llm.ainvoke(
        [
            HumanMessage(
                content=f"""Extract from this support investigation:
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
        domain="support",
        signals=parsed.get("signals", []),
        confidence=parsed.get("confidence", 0.5),
        raw_tool_outputs=[{"agent_output": final_message}],
        sub_question_answered=sub_question,
    )

    return {
        "support_findings": finding,
        "tool_call_log": [
            {
                "node": "support_agent",
                "sub_question": sub_question,
                "timestamp": datetime.utcnow().isoformat(),
            }
        ],
    }
