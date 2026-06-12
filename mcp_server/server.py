"""
mcp_server/server.py — FastMCP server entry point.

Exposes four MCP tools to any MCP-compatible client (Claude Code, Copilot, etc.).
All intelligence is in the LangGraph graph — this file is a pure adapter.
Transport: SSE on port settings.mcp_server_port. Started via `python -m mcp_server`.
"""

from fastmcp import FastMCP
from mcp_server.mcp_tools import diagnose, fix, recall, summarize

mcp = FastMCP(
    name="ecommerce-ops-agent",
    instructions=(
        "E-Commerce Operations AI Agent. "
        "Use 'diagnose' to investigate business issues, "
        "'fix' to propose and execute corrective actions (requires human approval), "
        "'recall' to retrieve similar past incidents, "
        "'summarize' for an executive business health summary."
    ),
)

mcp.tool()(diagnose)
mcp.tool()(summarize)
mcp.tool()(recall)
mcp.tool()(fix)

# Prompts

@mcp.prompt()
def diagnose_revenue_drop() -> str:
    return "Why did revenue drop today? Investigate sales, inventory, and marketing channels."

@mcp.prompt()
def diagnose_inventory_issue() -> str:
    return "Are there any inventory shortages or stockout events affecting sales today?"

@mcp.prompt()
def fix_stockout(product_id: str) -> str:
    return f"Create a restock order for product {product_id} and notify the warehouse team."

@mcp.prompt()
def recall_similar_incidents(issue: str) -> str:
    return f"Find past incidents similar to: {issue}"

@mcp.prompt()
def daily_health_summary() -> str:
    return "Give me an executive summary of today's e-commerce operations health across all channels."
