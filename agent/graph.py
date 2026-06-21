"""
agent/graph.py — LangGraph StateGraph topology for the E-Commerce Ops Agent.

This file owns ONLY the graph wiring: nodes, edges, conditional routing, and
Send()-based parallel fan-out. Node logic (Phase 3) will be imported here once
implemented; for now every node is a stub returning {}.
"""

from langgraph.graph import StateGraph, START, END
from langgraph.graph.state import CompiledStateGraph
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Send

from tools.registry import load_all_tools

from agent.state import OpsAgentState
from config import settings


# ---------------------------------------------------------------------------
# Node function imports — real implementations from Phase 3 modules.
# ---------------------------------------------------------------------------

from agent.orchestrator import run_orchestrator as orchestrator_node
from agent.specialists.sales import run_sales_agent as sales_node
from agent.specialists.inventory import run_inventory_agent as inventory_node
from agent.specialists.marketing import run_marketing_agent as marketing_node
from agent.specialists.support import run_support_agent as support_node
from agent.aggregator import run_aggregator as aggregator_node
from agent.reflection import run_reflection as reflection_node
from agent.hitl import run_hitl as hitl_node
from agent.action_executor import run_action_executor as action_executor_node
from agent.output_formatter import run_output_formatter as output_formatter_node


from memory.long_term import run_memory_writer as memory_writer_node
from memory.long_term import run_recall_node as recall_node


# ---------------------------------------------------------------------------
# Conditional edge functions — pure functions of state, no side effects.
# ---------------------------------------------------------------------------

def route_to_specialists(state: OpsAgentState) -> list[Send] | str:
    """Fan out to only the active specialists via Send().

    For 'recall' intent: short-circuits directly to recall_node (no specialists).
    For all other intents: fans out to active specialists via Send().
    """
    if state.get("intent") == "recall":
        return "recall_node"
    specialist_map = {
        "sales": "sales_node",
        "inventory": "inventory_node",
        "marketing": "marketing_node",
        "support": "support_node",
    }
    return [
        Send(specialist_map[s], state)
        for s in state.get("active_specialists", list(specialist_map.keys()))
        if s in specialist_map
    ]


def route_after_reflection(state: OpsAgentState) -> str:
    """Loop back to orchestrator if reflection failed and retries remain;
    otherwise advance to the HITL checkpoint.
    """
    if (
        not state.get("reflection_passed", False)
        and state.get("retry_count", 0) < settings.max_reflection_retries
    ):
        return "orchestrator_node"
    return "hitl_node"


def route_after_hitl(state: OpsAgentState) -> str:
    """Route 'fix' intents through the action executor; all others go directly
    to the output formatter (read-only intents: diagnose, recall, summarize).
    """
    if state.get("intent") == "fix":
        return "action_executor_node"
    return "output_formatter_node"


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------

def build_graph() -> CompiledStateGraph:
    """Construct and compile the full ops-agent StateGraph."""
    builder = StateGraph(OpsAgentState)

    # ------------------------------------------------------------------
    # Register nodes
    # ------------------------------------------------------------------
    builder.add_node("orchestrator_node", orchestrator_node)
    builder.add_node("sales_node", sales_node)
    builder.add_node("inventory_node", inventory_node)
    builder.add_node("marketing_node", marketing_node)
    builder.add_node("support_node", support_node)
    builder.add_node("aggregator_node", aggregator_node)
    builder.add_node("reflection_node", reflection_node)
    builder.add_node("hitl_node", hitl_node)
    builder.add_node("action_executor_node", action_executor_node)
    builder.add_node("memory_writer_node", memory_writer_node)
    builder.add_node("recall_node", recall_node)
    builder.add_node("output_formatter_node", output_formatter_node)

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    builder.add_edge(START, "orchestrator_node")

    # ------------------------------------------------------------------
    # Orchestrator → parallel specialist fan-out via Send()
    # The third argument is the list of valid destination node names so
    # LangGraph can validate the routing function's output at build time.
    # ------------------------------------------------------------------
    builder.add_conditional_edges(
        "orchestrator_node",
        route_to_specialists,
        ["sales_node", "inventory_node", "marketing_node", "support_node", "recall_node"],
    )

    # Recall short-circuit: skip specialists, aggregator, reflection, hitl
    builder.add_edge("recall_node", "output_formatter_node")

    # ------------------------------------------------------------------
    # All specialists converge on aggregator
    # LangGraph collects all Send() outputs before executing the next node.
    # ------------------------------------------------------------------
    builder.add_edge("sales_node", "aggregator_node")
    builder.add_edge("inventory_node", "aggregator_node")
    builder.add_edge("marketing_node", "aggregator_node")
    builder.add_edge("support_node", "aggregator_node")

    # ------------------------------------------------------------------
    # Aggregator → reflection
    # ------------------------------------------------------------------
    builder.add_edge("aggregator_node", "reflection_node")

    # ------------------------------------------------------------------
    # Reflection → conditional (retry loop or HITL)
    # ------------------------------------------------------------------
    builder.add_conditional_edges(
        "reflection_node",
        route_after_reflection,
        {"orchestrator_node": "orchestrator_node", "hitl_node": "hitl_node"},
    )

    # ------------------------------------------------------------------
    # HITL → conditional (action path or direct to output)
    # ------------------------------------------------------------------
    builder.add_conditional_edges(
        "hitl_node",
        route_after_hitl,
        {
            "action_executor_node": "action_executor_node",
            "output_formatter_node": "output_formatter_node",
        },
    )

    # ------------------------------------------------------------------
    # Action execution path
    # ------------------------------------------------------------------
    builder.add_edge("action_executor_node", "memory_writer_node")
    builder.add_edge("memory_writer_node", "output_formatter_node")

    # ------------------------------------------------------------------
    # Terminal edge — every path must reach END
    # ------------------------------------------------------------------
    builder.add_edge("output_formatter_node", END)

    # ------------------------------------------------------------------
    # Tool registry — populate before any node can run
    # ------------------------------------------------------------------
    load_all_tools()

    # ------------------------------------------------------------------
    # Checkpointer selection
    # ------------------------------------------------------------------
    if settings.checkpoint_backend == "postgres" and settings.database_url:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
        checkpointer = AsyncPostgresSaver.from_conn_string(dsn)
    else:
        checkpointer = MemorySaver()

    # Register custom state types so msgpack checkpoint serialisation
    # doesn't emit warnings (will be required in future LangGraph).
    allowed = [
        ("agent.state", "SpecialistFinding"),
        ("agent.state", "RootCause"),
        ("agent.state", "ProposedAction"),
        ("agent.state", "ExecutedAction"),
        ("agent.state", "PastIncident"),
        ("agent.state", "StructuredResponse"),
        ("agent.state", "SubQuestion"),
        ("agent.state", "OrchestratorDecision"),
        ("agent.state", "CorrelationMatrix"),
        ("agent.state", "PairCorrelation"),
        ("agent.state", "AggregatorOutput"),
    ]
    if hasattr(checkpointer, "allowed_msgpack_modules"):
        checkpointer.allowed_msgpack_modules = allowed

    return builder.compile(checkpointer=checkpointer)


# Module-level compiled graph — imported by the MCP server and tests as:
#   from agent.graph import graph
graph = build_graph()

__all__ = ["graph", "build_graph"]
