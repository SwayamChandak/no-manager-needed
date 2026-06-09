"""
eval/deepeval_setup.py — DeepEval configuration and per-node metric factories.

Uses AzureOpenAIModel (same credentials as the app) as the judge for all metrics.
Import the relevant factory from here in each LLM-calling node.

Design decisions for production correctness:
  1. Judge model is a singleton — stateless config object, safe to share.
  2. Metric factories return NEW instances on every call.
     Metrics store mutable state (.score, .reason) so they MUST NOT be shared
     across concurrent node invocations. Each specialist node imports its own
     factory (separate module ⟹ separate instances at decoration time), and
     the aggregator/formatter run sequentially so sharing is not an issue.
  3. FaithfulnessMetric is included for specialist nodes because their tool
     outputs provide real retrieval context to ground the check.
  4. Domain-specific GEval criteria give the judge precise rubrics rather than
     generic instructions, which reduces score variance.
  5. Thresholds are set at 0.6 (production floor) — 0.5 is the absolute minimum
     and is not suitable for a live system.

Nodes with LLM calls (instrumented):
  - orchestrator      → Routing Correctness (GEval)
  - sales             → AnswerRelevancy + TaskCompletion + Faithfulness + Sales GEval
  - inventory         → AnswerRelevancy + TaskCompletion + Faithfulness + Inventory GEval
  - marketing         → AnswerRelevancy + TaskCompletion + Faithfulness + Marketing GEval
  - support           → AnswerRelevancy + TaskCompletion + Faithfulness + Support GEval
  - aggregator        → AnswerRelevancy + Root Cause Quality (GEval)
  - output_formatter  → AnswerRelevancy + Response Clarity (GEval)

Nodes WITHOUT LLM calls (not instrumented):
  - reflection        — pure deterministic logic
  - hitl              — state management only
  - action_executor   — tool calls only
"""

from __future__ import annotations

from deepeval.metrics import (
    AnswerRelevancyMetric,
    FaithfulnessMetric,
    GEval,
    TaskCompletionMetric,
)
from deepeval.models import AzureOpenAIModel
from deepeval.test_case import SingleTurnParams

from config import settings

# ---------------------------------------------------------------------------
# Singleton judge — stateless, safe to share across metrics in one process.
# ---------------------------------------------------------------------------
_judge_instance: AzureOpenAIModel | None = None


def _judge() -> AzureOpenAIModel:
    global _judge_instance
    if _judge_instance is None:
        _judge_instance = AzureOpenAIModel(
            model=settings.azure_openai_deployment,
            deployment_name=settings.azure_openai_deployment,
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
            base_url=settings.azure_openai_endpoint,
            temperature=0,
            # Cap completion tokens — metric scores + reasoning never need more
            # than ~1 000 tokens. Without this, the model can exhaust its output
            # limit mid-JSON and cause a LengthFinishReasonError.
            generation_kwargs={"max_tokens": 1024},
        )
    return _judge_instance


# ---------------------------------------------------------------------------
# Orchestrator metrics
# ---------------------------------------------------------------------------

def orchestrator_metrics() -> list:
    """
    Evaluates whether the LLM correctly classified intent and routed to the
    right minimal set of specialist domains.
    Called once at module import time (orchestrator runs sequentially — no race).
    """
    j = _judge()
    return [
        GEval(
            name="Routing Correctness",
            criteria=(
                "Evaluate whether the orchestrator:\n"
                "1. Correctly classified the intent as one of: diagnose, fix, recall, summarize.\n"
                "2. Selected only the specialist domains (sales, inventory, marketing, support) "
                "that are genuinely relevant to the query — penalise over-routing.\n"
                "3. Wrote clear, targeted sub-questions for each selected specialist.\n"
                "Score 1.0 if all three are correct; deduct proportionally for each failure."
            ),
            evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT],
            model=j,
            threshold=0.6,
        ),
    ]


# ---------------------------------------------------------------------------
# Specialist metrics — domain-specific, with FaithfulnessMetric when
# retrieval_context is populated.
# ---------------------------------------------------------------------------

def _base_specialist_geval(name: str, domain_criteria: str) -> GEval:
    return GEval(
        name=name,
        criteria=domain_criteria,
        evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT],
        model=_judge(),
        threshold=0.6,
    )


def sales_metrics() -> list:
    """
    Metrics for the Sales specialist node.
    FaithfulnessMetric will use retrieval_context (tool outputs) if provided in
    the LLMTestCase.
    """
    j = _judge()
    return [
        AnswerRelevancyMetric(model=j, threshold=0.6),
        TaskCompletionMetric(model=j, threshold=0.6),
        FaithfulnessMetric(model=j, threshold=0.6),
        _base_specialist_geval(
            name="Sales Investigation Quality",
            domain_criteria=(
                "Evaluate the sales specialist's response:\n"
                "1. Does it directly address the sub-question about revenue, orders, or anomalies?\n"
                "2. Does it cite specific numbers, products, or date ranges from the retrieved data?\n"
                "3. Are the conclusions logically supported by the data — no hallucinated figures?\n"
                "4. Does it flag any anomalies or trends that are actually present in the data?\n"
                "Penalise vague answers that reference 'products' or 'revenue' without specifics."
            ),
        ),
    ]


def inventory_metrics() -> list:
    """Metrics for the Inventory specialist node."""
    j = _judge()
    return [
        AnswerRelevancyMetric(model=j, threshold=0.6),
        TaskCompletionMetric(model=j, threshold=0.6),
        FaithfulnessMetric(model=j, threshold=0.6),
        _base_specialist_geval(
            name="Inventory Investigation Quality",
            domain_criteria=(
                "Evaluate the inventory specialist's response:\n"
                "1. Does it directly address the sub-question about stock levels or restock needs?\n"
                "2. Does it cite specific product names, SKUs, quantities, or thresholds?\n"
                "3. Does it correctly identify which products are low-stock or at risk of stockout?\n"
                "4. Are restock recommendations grounded in the actual data retrieved?\n"
                "Penalise generic statements like 'some products need restocking' without specifics."
            ),
        ),
    ]


def marketing_metrics() -> list:
    """Metrics for the Marketing specialist node."""
    j = _judge()
    return [
        AnswerRelevancyMetric(model=j, threshold=0.6),
        TaskCompletionMetric(model=j, threshold=0.6),
        FaithfulnessMetric(model=j, threshold=0.6),
        _base_specialist_geval(
            name="Marketing Investigation Quality",
            domain_criteria=(
                "Evaluate the marketing specialist's response:\n"
                "1. Does it address the sub-question about campaign performance or promotions?\n"
                "2. Does it cite specific campaign names, channels, spend, ROAS, or conversion rates?\n"
                "3. Are paused campaigns correctly identified and explained?\n"
                "4. Are conclusions grounded in the retrieved metrics — no invented numbers?\n"
                "Penalise responses that reference campaigns without naming them or citing metrics."
            ),
        ),
    ]


def support_metrics() -> list:
    """Metrics for the Support specialist node."""
    j = _judge()
    return [
        AnswerRelevancyMetric(model=j, threshold=0.6),
        TaskCompletionMetric(model=j, threshold=0.6),
        FaithfulnessMetric(model=j, threshold=0.6),
        _base_specialist_geval(
            name="Support Investigation Quality",
            domain_criteria=(
                "Evaluate the support specialist's response:\n"
                "1. Does it address the sub-question about complaint volume, issues, or sentiment?\n"
                "2. Does it cite specific complaint counts, issue categories, or sentiment scores?\n"
                "3. Does it correctly identify the most common issues or at-risk products/categories?\n"
                "4. Are findings grounded in the retrieved CRM data — no fabricated ticket counts?\n"
                "Penalise vague answers that don't cite actual numbers from the retrieved data."
            ),
        ),
    ]


# ---------------------------------------------------------------------------
# Aggregator metrics
# ---------------------------------------------------------------------------

def aggregator_metrics() -> list:
    """
    Evaluates cross-domain correlation quality and root-cause reasoning.
    Aggregator runs sequentially — single instance at decoration time is fine.
    """
    j = _judge()
    return [
        AnswerRelevancyMetric(model=j, threshold=0.6),
        GEval(
            name="Root Cause Quality",
            criteria=(
                "Evaluate the aggregator's analysis:\n"
                "1. Does it draw meaningful cross-domain connections (e.g. low stock → missed sales)?\n"
                "2. Are root causes ranked by plausibility with well-reasoned confidence scores?\n"
                "3. Do the proposed actions logically follow from the identified root causes?\n"
                "4. Is the summary factually grounded in the specialist findings provided?\n"
                "Score 1.0 for thorough multi-domain correlation with specific, actionable proposals; "
                "deduct for generic conclusions or actions disconnected from the evidence."
            ),
            evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT],
            model=j,
            threshold=0.6,
        ),
    ]


# ---------------------------------------------------------------------------
# Output formatter metrics
# ---------------------------------------------------------------------------

def output_formatter_metrics() -> list:
    """
    Evaluates whether the final user-facing response is relevant, clear, and
    grounded — no hallucinated product names, figures, or actions.
    Output formatter runs sequentially — single instance is fine.
    """
    j = _judge()
    return [
        AnswerRelevancyMetric(model=j, threshold=0.6),
        GEval(
            name="Response Clarity",
            criteria=(
                "Evaluate the final user-facing response:\n"
                "1. Does it directly and completely answer the user's original query?\n"
                "2. Are specific product names, figures, campaign names, or ticket counts cited "
                "when they appear in the context — not replaced with vague generalisations?\n"
                "3. Is the intent correctly reflected: diagnose responses propose (not execute) "
                "actions; fix responses confirm what was executed.\n"
                "4. Is the response free of hallucinated details not found in the context?\n"
                "5. Is it concise — no more than 5 sentences for a typical query?\n"
                "Deduct for vagueness, wrong intent framing, or any fabricated specifics."
            ),
            evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT],
            model=j,
            threshold=0.6,
        ),
    ]
