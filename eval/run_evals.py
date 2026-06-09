"""
eval/run_evals.py — Standalone DeepEval batch evaluation script.

Run with:
    python eval/run_evals.py

This script:
1. Boots the DB connection (same as the main app).
2. Runs a fixed dataset of diagnostic queries through the full graph.
3. Uses evals_iterator() so DeepEval snapshots every trace + span score
   to a local test_run_*.json file.
4. After completion, run `deepeval inspect` to open the TUI.

Only diagnostic (read-only) queries are used here so the graph never
hits the HITL interrupt — the eval loop completes end-to-end automatically.
"""

import asyncio
import sys
import uuid
from datetime import datetime

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from deepeval.dataset import EvaluationDataset, Golden
from deepeval.tracing import observe, update_current_trace
from langchain_core.messages import HumanMessage

# Bootstrap DB and settings before importing graph
from config import settings
from db.connection import configure as configure_db

configure_db(settings.database_url)

# Import graph AFTER DB is configured
from agent.graph import graph  # noqa: E402  (graph is a compiled StateGraph)


# ---------------------------------------------------------------------------
# Goldens — representative diagnostic queries (no "fix" intent so HITL
# is never triggered and evals complete without human input).
# ---------------------------------------------------------------------------
GOLDENS = [
    Golden(input="What are the top selling products today?"),
    Golden(input="Which products are running low on stock?"),
    Golden(input="Are there any active marketing campaigns right now?"),
    Golden(input="How many customer complaints were raised today?"),
    Golden(input="Summarize today's overall business health"),
    # Golden(input="Which product has the highest revenue this week?"),
    # Golden(input="Are there any sales anomalies detected today?"),
    # Golden(input="What is the current inventory status for all products?"),
]


def _initial_state(query: str, session_id: str) -> dict:
    """Build the initial LangGraph state for an eval run."""
    return {
        "session_id": session_id,
        "user_query": query,
        "intent": "diagnose",
        "active_specialists": ["sales", "inventory", "marketing", "support"],
        "retry_count": 0,
        "sales_findings": None,
        "inventory_findings": None,
        "marketing_findings": None,
        "support_findings": None,
        "root_causes": [],
        "correlation_matrix": {},
        "reflection_notes": [],
        "reflection_passed": False,
        "proposed_actions": [],
        "approved_actions": [],
        "executed_actions": [],
        "retrieved_memories": [],
        "final_response": None,
        "messages": [HumanMessage(content=query)],
        "tool_call_log": [],
        "timestamp": datetime.utcnow().isoformat(),
    }


@observe()
async def run_eval_query(query: str) -> str:
    """
    Top-level @observe trace wrapping one full graph invocation.
    Child nodes already have @observe(metrics=[...]) so they create
    scored sub-spans automatically.
    """
    session_id = str(uuid.uuid4())
    state = _initial_state(query, session_id)

    result = await graph.ainvoke(
        state,
        config={"configurable": {"thread_id": session_id}},
    )

    final = result.get("final_response")
    output = final.explanation if final else "No response generated"

    # Register the top-level trace input/output for DeepEval
    update_current_trace(input=query, output=output)

    return output


async def main() -> None:
    dataset = EvaluationDataset(goldens=GOLDENS)
    total = len(GOLDENS)
    passed = 0
    failed = 0

    print(f"\nRunning {total} evals — this may take a few minutes...\n")
    start = asyncio.get_event_loop().time()

    for i, golden in enumerate(dataset.evals_iterator(), 1):
        print(f"  [{i}/{total}] {golden.input[:70]}")
        try:
            task = asyncio.create_task(run_eval_query(golden.input))
            dataset.evaluate(task)
            passed += 1
        except Exception as exc:
            print(f"         ✗ FAILED: {exc}")
            failed += 1

    elapsed = asyncio.get_event_loop().time() - start
    print(
        f"\n{'─' * 60}\n"
        f"  Completed {total} evals in {elapsed:.1f}s  "
        f"({passed} passed, {failed} failed)\n"
        f"{'─' * 60}\n"
        f"  Run `deepeval inspect` to view per-node scores in the TUI.\n"
    )


if __name__ == "__main__":
    asyncio.run(main())
