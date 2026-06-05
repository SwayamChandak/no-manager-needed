import json
import re
from datetime import date, datetime

from langchain_core.messages import HumanMessage
from langchain_openai import AzureChatOpenAI
from langgraph.prebuilt import create_react_agent

from agent.state import OpsAgentState, SpecialistFinding
from config import settings
from tools.analytics import (
    detect_anomaly,
    get_order_volume,
    get_revenue_by_product,
    get_revenue_by_region,
    get_revenue_timeseries,
)

llm = AzureChatOpenAI(
    azure_endpoint=settings.azure_openai_endpoint,
    api_key=settings.azure_openai_api_key,
    azure_deployment=settings.azure_openai_deployment,
    api_version=settings.azure_openai_api_version,
    temperature=0,
)

SALES_SYSTEM_PROMPT = """You are the Sales & Revenue specialist agent for an e-commerce operations system.
You have access to tools that retrieve sales metrics, order volumes, revenue breakdowns, and anomaly detection.
When given a sub-question, investigate thoroughly using the available tools and return a comprehensive finding.
Always use today's date or the date mentioned in the query. Default date: {today}.
Be specific about which products, regions, and time windows you investigated.
"""

sales_tools = [
    get_revenue_timeseries,
    get_order_volume,
    get_revenue_by_product,
    get_revenue_by_region,
    detect_anomaly,
]


def run_sales_agent(state: OpsAgentState) -> dict:
    """Sales specialist node — investigates revenue and order signals."""
    sub_question = state.get("user_query", "")
    for msg in reversed(state.get("messages", [])):
        if hasattr(msg, "content") and "[SALES_SUBQUESTION]" in str(msg.content):
            sub_question = str(msg.content).replace("[SALES_SUBQUESTION]", "").strip()
            break

    today = date.today().isoformat()
    system_prompt = SALES_SYSTEM_PROMPT.format(today=today)

    agent = create_react_agent(llm, sales_tools, prompt=system_prompt)
    result = agent.invoke({"messages": [HumanMessage(content=sub_question)]})

    final_message = result["messages"][-1].content if result.get("messages") else ""

    summary_prompt = f"""Based on this sales investigation result, extract:
1. A list of 3-5 key signals/observations (as short strings)
2. A confidence score 0.0-1.0 for how conclusive the findings are

Investigation result:
{final_message}

Return JSON: {{"signals": ["...", "..."], "confidence": 0.0}}"""

    summary_response = llm.invoke([HumanMessage(content=summary_prompt)])
    json_match = re.search(r"\{.*\}", summary_response.content, re.DOTALL)
    parsed = (
        json.loads(json_match.group())
        if json_match
        else {"signals": [final_message[:200]], "confidence": 0.5}
    )

    finding = SpecialistFinding(
        domain="sales",
        signals=parsed.get("signals", []),
        confidence=parsed.get("confidence", 0.5),
        raw_tool_outputs=[{"agent_output": final_message}],
        sub_question_answered=sub_question,
    )

    return {
        "sales_findings": finding,
        "tool_call_log": [
            {
                "node": "sales_agent",
                "sub_question": sub_question,
                "timestamp": datetime.utcnow().isoformat(),
            }
        ],
    }
