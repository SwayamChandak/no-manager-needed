from datetime import datetime

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import AzureChatOpenAI
from deepeval.tracing import observe, update_current_span
from deepeval.test_case import LLMTestCase

from agent.state import AggregatorOutput, OpsAgentState
from config import settings
try:
    from eval.deepeval_setup import aggregator_metrics
except ModuleNotFoundError:
    aggregator_metrics = None

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
      "action_type": "restock|apply_discount|pause_campaign|relaunch_campaign|launch_campaign|create_ticket",
      "parameters": "{{\"key\": \"value\"}}",
      "justification": "...",
      "estimated_impact": "..."
    }}
  ],
  "summary": "One paragraph summary of what happened and why."
}}

Action type reference — use ONLY these exact strings:
- "restock": submit a restock order. parameters: {{"product_name": "the exact product name", "quantity": N}}
- "apply_discount": apply a temporary discount. parameters: {{"product_ids": ["..."], "discount_pct": N, "duration_hours": N}}
- "pause_campaign": pause an active campaign by its name. parameters: {{"campaign_name": "COPY the 'name' field VERBATIM from the raw tool data — do NOT paraphrase, abbreviate, or guess. Example: if raw tool data shows \"name\": \"Summer Tech Sale\", use \"Summer Tech Sale\" exactly.", "reason": "..."}}
- "relaunch_campaign": reactivate a paused or inactive campaign. parameters: {{"campaign_id": "..."}}
- "launch_campaign": create a brand-new campaign and optionally apply a product discount. parameters: {{"name": "...", "channel": "paid_search|social_ads|email|organic|display|affiliate", "budget": N, "product_names": ["Laptop Pro 15"], "discount_pct": N, "duration_hours": N}}
- "create_ticket": create a support ticket. parameters: {{"issue_description": "...", "priority": "low|medium|high|critical"}}

CRITICAL: When proposing a "pause_campaign" action, you MUST copy the campaign "name" field character-for-character from the raw tool data in the findings above. Never paraphrase or shorten it.
"""


def _build_aggregator_output_text(output: AggregatorOutput) -> str:
    """
    Flatten all aggregator output fields into a single text block for DeepEval.
    The Root Cause Quality metric checks for cross-domain connections, ranked
    root causes, and proposed actions — passing only output.summary omits those.
    """

    lines: list[str] = [f"Summary: {output.summary}"]

    if output.root_causes:
        lines.append("\nRoot Causes (ranked by confidence):")
        for i, rc in enumerate(output.root_causes, 1):
            domains = ", ".join(rc.supporting_domains) if rc.supporting_domains else "—"
            evidence = "; ".join(rc.evidence[:3]) if rc.evidence else "—"
            lines.append(
                f"  {i}. [{rc.confidence:.0%}] {rc.description}\n"
                f"     Domains: {domains}\n"
                f"     Evidence: {evidence}"
            )

    if output.proposed_actions:
        lines.append("\nProposed Actions:")
        for pa in output.proposed_actions:
            lines.append(
                f"  - {pa.action_type}: {pa.justification} "
                f"(impact: {pa.estimated_impact})"
            )

    # Include non-trivial cross-domain correlations
    matrix = output.correlation_matrix
    if matrix:
        linked = [
            f"{pair}: {info.explanation}"
            for pair, info in [
                ("sales↔inventory", matrix.sales_inventory),
                ("sales↔marketing", matrix.sales_marketing),
                ("inventory↔marketing", matrix.inventory_marketing),
                ("sales↔support", matrix.sales_support),
            ]
            if info and info.linked
        ]
        if linked:
            lines.append("\nCross-domain links detected:")
            lines.extend(f"  • {link}" for link in linked)

    return "\n".join(lines)


@observe(metrics=aggregator_metrics())
def run_aggregator(state: OpsAgentState) -> dict:
    """Aggregator node — cross-domain correlation and root cause ranking."""
    findings = {}
    for domain in ["sales", "inventory", "marketing", "support"]:
        finding = state.get(f"{domain}_findings")
        if finding is not None:
            findings[domain] = finding

    if findings:
        parts = []
        for domain, f in findings.items():
            part = (
                f"=== {domain.upper()} FINDINGS ===\n"
                f"Signals: {', '.join(f.signals)}\n"
                f"Confidence: {f.confidence}\n"
                f"Sub-question answered: {f.sub_question_answered}"
            )
            if f.raw_tool_outputs:
                import json as _json
                raw_summary = _json.dumps(f.raw_tool_outputs, default=str)
                # Truncate very large payloads to avoid token limits
                if len(raw_summary) > 3000:
                    raw_summary = raw_summary[:3000] + "... [truncated]"
                part += f"\nRaw tool data: {raw_summary}"
            parts.append(part)
        findings_text = "\n\n".join(parts)
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

    update_current_span(
        test_case=LLMTestCase(
            input=state.get("user_query", ""),
            actual_output=_build_aggregator_output_text(output),
        )
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
