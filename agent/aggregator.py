from datetime import datetime

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import AzureChatOpenAI

from agent.state import AggregatorOutput, OpsAgentState, CorrelationMatrix, PairCorrelation
from config import settings

llm = AzureChatOpenAI(
    azure_endpoint=settings.azure_openai_endpoint,
    api_key=settings.azure_openai_api_key,
    azure_deployment=settings.azure_openai_deployment,
    api_version=settings.azure_openai_api_version,
    temperature=0,
)

AGGREGATOR_PROMPT = """You are the cross-domain aggregator for an e-commerce AI ops system.
You receive findings from up to 4 specialist agents (sales, inventory, marketing, support).
Your job:
1. Build a correlation matrix — for each pair of domains present, determine if their signals are causally linked (yes/no + explanation)
2. Rank root causes by confidence (0.0-1.0), citing which domains support each cause
3. Propose 1-3 concrete actions based on the findings

Specialist findings:
{findings_text}

User's original query: {user_query}

Return structured output matching this schema:
{{
  "correlation_matrix": {{
    "sales_inventory": {{"linked": true, "explanation": "..."}},
    "sales_marketing": {{"linked": true, "explanation": "..."}},
    "sales_support": {{"linked": true, "explanation": "..."}},
    "inventory_marketing": {{"linked": true, "explanation": "..."}},
    "inventory_support": {{"linked": true, "explanation": "..."}},
    "marketing_support": {{"linked": true, "explanation": "..."}}
  }},
  "root_causes": [
    {{
      "description": "...",
      "confidence": 0.0,
      "supporting_domains": ["sales", "inventory"],
      "evidence": ["signal 1", "signal 2"]
    }}
  ],
  "proposed_actions": [
    {{
      "action_type": "restock|apply_discount|pause_campaign|create_ticket",
      "parameters": "{{\"key\": \"value\"}}",
      "justification": "...",
      "estimated_impact": "..."
    }}
  ],
  "summary": "One paragraph summary of what happened and why."
}}
"""


def run_aggregator(state: OpsAgentState) -> dict:
    """Aggregator node — cross-domain correlation and root cause ranking."""
    findings = {}
    for domain in ["sales", "inventory", "marketing", "support"]:
        finding = state.get(f"{domain}_findings")
        if finding is not None:
            findings[domain] = finding

    if findings:
        findings_text = "\n\n".join(
            f"=== {domain.upper()} FINDINGS ===\n"
            f"Signals: {', '.join(f.signals)}\n"
            f"Confidence: {f.confidence}\n"
            f"Sub-question answered: {f.sub_question_answered}"
            for domain, f in findings.items()
        )
    else:
        findings_text = "No specialist findings available."

    structured_llm = llm.with_structured_output(AggregatorOutput)
    prompt = AGGREGATOR_PROMPT.format(
        findings_text=findings_text,
        user_query=state.get("user_query", ""),
    )

    output: AggregatorOutput = structured_llm.invoke(
        [
            SystemMessage(content=prompt),
            HumanMessage(content="Analyze the findings and return the structured output."),
        ]
    )

    return {
        "correlation_matrix": output.correlation_matrix.model_dump(),
        "root_causes": output.root_causes,
        "proposed_actions": output.proposed_actions,
        "tool_call_log": [
            {
                "node": "aggregator",
                "domains_present": list(findings.keys()),
                "root_causes_count": len(output.root_causes),
                "timestamp": datetime.utcnow().isoformat(),
            }
        ],
    }
