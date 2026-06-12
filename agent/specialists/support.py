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
from eval.deepeval_setup import support_metrics
from tools.registry import get_tools_for_agent

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


@observe(metrics=support_metrics())
async def run_support_agent(state: OpsAgentState) -> dict:
    """Support specialist node."""
    sub_question = state.get("user_query", "")
    for msg in reversed(state.get("messages", [])):
        if hasattr(msg, "content") and "[SUPPORT_SUBQUESTION]" in str(msg.content):
            sub_question = str(msg.content).replace("[SUPPORT_SUBQUESTION]", "").strip()
            break

    today = date.today().isoformat()
    agent = create_react_agent(
        llm, get_tools_for_agent("support"), prompt=SUPPORT_SYSTEM_PROMPT.format(today=today)
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
        "support_findings": finding,
        "tool_call_log": [
            {
                "node": "support_agent",
                "sub_question": sub_question,
                "timestamp": datetime.utcnow().isoformat(),
            }
        ],
    }
