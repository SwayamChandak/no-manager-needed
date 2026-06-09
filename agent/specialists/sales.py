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
from eval.deepeval_setup import sales_metrics
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


@observe(metrics=sales_metrics())
async def run_sales_agent(state: OpsAgentState) -> dict:
    """Sales specialist node — investigates revenue and order signals."""
    sub_question = state.get("user_query", "")
    for msg in reversed(state.get("messages", [])):
        if hasattr(msg, "content") and "[SALES_SUBQUESTION]" in str(msg.content):
            sub_question = str(msg.content).replace("[SALES_SUBQUESTION]", "").strip()
            break

    today = date.today().isoformat()
    system_prompt = SALES_SYSTEM_PROMPT.format(today=today)

    agent = create_react_agent(llm, sales_tools, prompt=system_prompt)
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

    summary_prompt = f"""Based on this sales investigation result, extract:
1. A list of 3-5 key signals/observations (as short strings)
2. A confidence score 0.0-1.0 for how conclusive the findings are

Investigation result:
{final_message}

Return JSON: {{"signals": ["...", "..."], "confidence": 0.0}}"""

    summary_response = await llm.ainvoke([HumanMessage(content=summary_prompt)])
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
        "sales_findings": finding,
        "tool_call_log": [
            {
                "node": "sales_agent",
                "sub_question": sub_question,
                "timestamp": datetime.utcnow().isoformat(),
            }
        ],
    }
