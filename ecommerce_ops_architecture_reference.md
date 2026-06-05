# E-Commerce AI Ops Agent — Architecture Reference
## MCP-First, LangGraph-Powered, Production-Grade

---

## 1. System Overview

This system is an AI-powered e-commerce operations manager. A business user (or an IDE agent like Claude Code / GitHub Copilot) sends natural language queries — "Why did sales drop yesterday?", "Fix the issue.", "What did we do last time?" — and the system investigates, explains, proposes actions, and executes them only after human approval.

The architecture has two layers:

- **Outer layer**: An MCP server that exposes a clean set of tools to any MCP-compatible client (Claude Code, Copilot, a chat UI, a custom dashboard).
- **Inner layer**: A LangGraph multi-agent system that does the actual reasoning, tool-calling, memory retrieval, and action execution.

The MCP server is a thin adapter. It does no reasoning itself. All intelligence lives in the LangGraph graph.

---

## 2. Technology Stack

| Concern | Library / Tool |
|---|---|
| Agent graph | `langgraph` (StateGraph, Send, interrupt) |
| LLM calls | `langchain-anthropic` or `langchain-openai` |
| Tool definitions | `langchain-core` `@tool` decorator |
| MCP server | `fastmcp` (Python) |
| MCP transport | stdio (local dev), SSE or HTTP (production) |
| Checkpoint store | `langgraph-checkpoint-sqlite` (dev), `-postgres` (prod) |
| Short-term memory | LangGraph `TypedDict` state |
| Long-term memory | `chromadb` (dev), Qdrant or Pinecone (prod) |
| Embeddings | `langchain-openai` `OpenAIEmbeddings` |
| Structured output | Pydantic v2 models |
| Observability | LangSmith (`LANGCHAIN_TRACING_V2=true`) |
| API layer (HITL) | `fastapi` + `uvicorn` |
| Config | `pydantic-settings`, `.env` |

---

## 3. Repository Structure

```
ecommerce-ops-agent/
├── mcp_server/
│   ├── server.py              # FastMCP server — entry point for all MCP clients
│   ├── tools.py               # MCP tool definitions (diagnose, fix, recall, summarize)
│   └── schemas.py             # Pydantic models for MCP tool inputs/outputs
│
├── agent/
│   ├── graph.py               # LangGraph StateGraph definition — the master graph
│   ├── state.py               # TypedDict for graph state
│   ├── orchestrator.py        # Orchestrator node — intent parsing, routing, synthesis
│   ├── aggregator.py          # Aggregator node — cross-domain correlation
│   ├── reflection.py          # Reflection node — gap detection, re-routing
│   ├── hitl.py                # HITL interrupt logic, checkpoint resume
│   └── specialists/
│       ├── sales.py           # Sales specialist sub-graph
│       ├── inventory.py       # Inventory specialist sub-graph
│       ├── marketing.py       # Marketing specialist sub-graph
│       └── support.py         # Support specialist sub-graph
│
├── tools/
│   ├── analytics.py           # Sales/revenue metrics tools
│   ├── inventory.py           # Stock level tools
│   ├── crm.py                 # Customer complaints, refunds, reviews tools
│   ├── campaigns.py           # Campaign performance tools
│   ├── actions.py             # Action executor tools (restock, discount, pause)
│   └── mock_data.py           # Realistic mock data layer
│
├── memory/
│   ├── short_term.py          # LangGraph state helpers
│   ├── long_term.py           # Vector store read/write, episode management
│   └── schemas.py             # Pydantic models for memory records
│
├── api/
│   └── hitl_api.py            # FastAPI endpoints: /approve, /reject, /pending
│
├── observability/
│   └── callbacks.py           # LangSmith callback handler, custom metrics
│
├── eval/
│   ├── test_scenarios.py      # Evaluation scenarios (the 40+ business questions)
│   ├── test_graph.py          # Unit tests for individual nodes
│   └── eval_runner.py         # LangSmith eval runner
│
├── config.py                  # Pydantic settings, env var loading
└── main.py                    # Starts MCP server + FastAPI HITL server together
```

---

## 4. MCP Server — Outer Layer

**File**: `mcp_server/server.py`

The MCP server exposes exactly four tools. Each tool is a thin wrapper that invokes the LangGraph graph and returns a structured result. The server runs as a single process. MCP clients connect via stdio (Claude Code) or SSE (web clients).

### Tool: `diagnose`

```
Input:  { "question": str, "session_id": str }
Output: DiagnoseResult { finding, root_causes, confidence, supporting_data, recommended_actions }
```

Invokes the full LangGraph graph in "diagnose" mode. Runs all four specialist agents in parallel. Returns a structured finding with ranked root causes and cross-domain correlation. Does NOT execute any actions. Safe to call freely.

### Tool: `fix`

```
Input:  { "action_plan": ActionPlan, "session_id": str }
Output: FixResult { status: "awaiting_approval" | "executed" | "rejected", actions_taken, summary }
```

Invokes the graph in "fix" mode. The graph will hit the HITL interrupt checkpoint and return `status: "awaiting_approval"` with the proposed actions listed. The MCP client renders this for the human. The human approves or rejects via the HITL API (or by calling this tool again with `approved: true`). On approval, the graph resumes from its checkpoint and executes. This is the only tool that mutates state.

### Tool: `recall`

```
Input:  { "scenario_description": str, "top_k": int = 3 }
Output: RecallResult { incidents: List[PastIncident], summary }
```

Queries the long-term vector store for similar past incidents. Returns the top-k most semantically similar incidents with their root causes, actions taken, and outcomes. Does not invoke the LangGraph graph at all — pure memory retrieval.

### Tool: `summarize`

```
Input:  { "date_range": str, "focus_areas": List[str] }
Output: SummaryResult { executive_summary, health_score, top_issues, recommended_actions }
```

Invokes the graph in "summarize" mode. Pulls data from all four domains and produces an executive summary suitable for a business report.

---

## 5. LangGraph Agent Graph — Inner Layer

**File**: `agent/graph.py`

The graph is a `StateGraph` with the following node sequence:

```
[START]
  → orchestrator
  → [parallel via Send()] → sales_agent, inventory_agent, marketing_agent, support_agent
  → aggregator
  → reflection                  ← loops back to orchestrator if gaps detected
  → hitl_checkpoint             ← suspends here for action approval
  → action_executor             ← only reached after approval
  → memory_writer
  → output_formatter
[END]
```

Conditional edges:
- After `reflection`: if reflection flags missing data → back to `orchestrator` (max 2 retries). Else → `hitl_checkpoint`.
- After `hitl_checkpoint`: if intent was diagnose/recall/summarize → skip to `output_formatter`. If intent was fix → proceed to `action_executor`.
- After `action_executor`: always → `memory_writer`.

### 5.1 Graph State

**File**: `agent/state.py`

```python
class OpsAgentState(TypedDict):
    # Input
    session_id: str
    user_query: str
    intent: str                    # "diagnose" | "fix" | "recall" | "summarize"
    
    # Routing
    active_specialists: List[str]  # which agents to invoke
    retry_count: int
    
    # Specialist outputs
    sales_findings: Optional[SpecialistFinding]
    inventory_findings: Optional[SpecialistFinding]
    marketing_findings: Optional[SpecialistFinding]
    support_findings: Optional[SpecialistFinding]
    
    # Aggregation
    root_causes: List[RootCause]   # ranked by confidence
    correlation_matrix: Dict       # cross-domain signal correlations
    
    # Reflection
    reflection_notes: List[str]    # gaps or weak conclusions found
    reflection_passed: bool
    
    # Actions
    proposed_actions: List[ProposedAction]
    approved_actions: List[ProposedAction]
    executed_actions: List[ExecutedAction]
    
    # Memory
    retrieved_memories: List[PastIncident]
    
    # Output
    final_response: Optional[StructuredResponse]
    
    # Metadata
    messages: List[BaseMessage]    # LangChain message history
    tool_call_log: List[Dict]
    timestamp: str
```

### 5.2 Orchestrator Node

**File**: `agent/orchestrator.py`

The orchestrator does three things depending on where in the graph it is called:

**On first entry** (from START):
- Parses user intent into one of: `diagnose`, `fix`, `recall`, `summarize`.
- Determines which specialist agents are relevant (e.g. a pure stock question routes only to inventory; a root-cause question routes to all four).
- Retrieves relevant long-term memories and injects them into state.
- Returns a `Send()` list to fan out to the relevant specialists in parallel.

**On re-entry** (from reflection loop):
- Reads reflection notes to understand what was missing.
- Dispatches targeted follow-up `Send()` calls to specific specialists with refined sub-questions.

**On synthesis** (after aggregation):
- Combines all specialist findings and the correlation matrix.
- Writes the final coherent explanation and recommended actions into state.
- Uses a structured output prompt with Pydantic parsing.

Implementation note: the orchestrator uses `with_structured_output(OrchestratorDecision)` on the LLM call for the routing step to guarantee parseable output.

### 5.3 Specialist Agents

**Files**: `agent/specialists/*.py`

Each specialist is its own `StateGraph` compiled as a subgraph. They share a common pattern:

```
[START] → analyst_node → [tool loop via ToolNode] → summarizer_node → [END]
```

The `analyst_node` is a ReAct-style LLM node. It receives a sub-question from the orchestrator (e.g. "Were any top-selling products out of stock yesterday? Did stock issues correlate with the revenue drop?") and calls its assigned tools in a loop until it has enough information.

The `summarizer_node` formats the raw tool results and LLM reasoning into a `SpecialistFinding` Pydantic model.

Each specialist has access only to its own domain's tools:
- **Sales agent**: `get_revenue_timeseries`, `get_order_volume`, `get_revenue_by_product`, `get_revenue_by_region`, `detect_anomaly`
- **Inventory agent**: `get_stock_levels`, `get_stockout_events`, `get_viewed_not_purchased`, `get_restock_recommendations`
- **Marketing agent**: `get_campaign_performance`, `get_channel_breakdown`, `get_paused_campaigns`, `get_promotion_schedule`
- **Support agent**: `get_complaint_volume`, `get_refund_rate`, `get_review_sentiment`, `get_common_issues`

Tool implementations live in `tools/` and are decorated with `@tool`. They call mock data during development. Swapping to real APIs requires changing only the function body — the tool name and schema stay the same.

### 5.4 Aggregator Node

**File**: `agent/aggregator.py`

Receives all four `SpecialistFinding` objects (some may be None if that specialist was not invoked). Produces:

1. A **correlation matrix**: for each pair of domains, does an LLM-assisted analysis of whether the signals are causally linked. Example: "Sales dropped 30% at 14:00. Inventory agent reports 'Laptop Pro' went out of stock at 13:45. These are likely causally linked."

2. A **ranked root cause list**: each `RootCause` has a description, confidence score (0.0–1.0), supporting domains, and supporting evidence.

3. A **proposed action list**: one or more `ProposedAction` objects derived from the findings. Each action has a type (`restock`, `run_discount`, `pause_campaign`, `create_ticket`), parameters, justification, and estimated impact.

The aggregator uses a structured output prompt. It does NOT call any tools.

### 5.5 Reflection Node

**File**: `agent/reflection.py`

Checks the quality of the aggregation before proceeding to HITL or output. Specifically:

- Are any root causes below the confidence threshold (default: 0.4)?
- Are there specialist findings that directly contradict each other without explanation?
- Did any specialist return empty results when data was expected?
- Is the proposed action list empty for a `fix` intent?

If any check fails, the node writes `reflection_notes` into state, sets `reflection_passed = False`, and the conditional edge routes back to the orchestrator with the specific gaps described. The orchestrator then dispatches targeted sub-questions.

If all checks pass, `reflection_passed = True` and the graph proceeds.

Maximum retry count is 2 (configurable). On the third pass, reflection always passes to avoid infinite loops, but flags low confidence in the output.

### 5.6 HITL Checkpoint

**File**: `agent/hitl.py`

Uses LangGraph's `interrupt()` primitive. When the graph reaches this node:

1. If intent is `diagnose`, `recall`, or `summarize`: no interrupt. The graph passes through and proceeds to output.

2. If intent is `fix`: the node calls `interrupt({"proposed_actions": state["proposed_actions"]})`. The graph suspends. State is serialized to the checkpoint store.

3. The MCP tool returns `status: "awaiting_approval"` to the MCP client with the proposed actions listed.

4. The human (in IDE or UI) approves or rejects. The HITL FastAPI endpoint at `/hitl/approve/{session_id}` or `/hitl/reject/{session_id}` is called.

5. On approval, the graph resumes via `graph.invoke(None, config={"configurable": {"thread_id": session_id}})`. The `interrupt()` returns the approval decision, which is written to `state["approved_actions"]`.

6. On rejection, the graph resumes and routes to output with `status: "rejected"`. No mutations occur.

Checkpoint persistence: in development use `MemorySaver`. In production use `AsyncPostgresSaver` from `langgraph-checkpoint-postgres`. The thread_id is the `session_id` passed from the MCP client.

### 5.7 Action Executor

**File**: `agent/graph.py` (inline node using tools from `tools/actions.py`)

Only reached after HITL approval. Iterates over `state["approved_actions"]` and calls the appropriate action tool for each:

- `restock_product(product_id, quantity)` — calls inventory management API
- `apply_discount(product_ids, discount_pct, duration_hours)` — calls pricing API
- `pause_campaign(campaign_id, reason)` — calls ads platform API
- `create_support_ticket(issue_description, priority)` — calls CRM API

Each action tool returns an `ExecutedAction` with status, timestamp, and any API response. All executed actions are appended to `state["executed_actions"]`.

### 5.8 Memory Writer

**File**: `memory/long_term.py`

After every completed run (whether or not actions were taken), writes an episodic record to the vector store:

```python
class IncidentRecord(BaseModel):
    incident_id: str
    timestamp: str
    query: str
    intent: str
    root_causes: List[str]
    actions_proposed: List[str]
    actions_approved: List[str]
    actions_executed: List[str]
    outcome_summary: str
    embedding_text: str          # concatenation of query + root_causes + actions
```

The `embedding_text` field is embedded with `OpenAIEmbeddings` and stored in Chroma (dev) or Qdrant (prod). Retrieval in the `recall` tool uses cosine similarity with `top_k` results.

---

## 6. Tool Layer

**Directory**: `tools/`

All tools follow the same pattern:

```python
from langchain_core.tools import tool
from tools.mock_data import MockDataStore

@tool
def get_revenue_timeseries(date: str, granularity: str = "hourly") -> dict:
    """
    Returns revenue timeseries for a given date.
    date: ISO date string (e.g. '2024-01-15')
    granularity: 'hourly' or 'daily'
    Returns: { "date": str, "data_points": [{"time": str, "revenue": float}], "total": float }
    """
    return MockDataStore.get_revenue(date, granularity)
```

The docstring is critical — LangChain passes it to the LLM as the tool description. Write it precisely.

**Mock data** (`tools/mock_data.py`) should be a realistic static dataset that simulates a plausible business scenario — for example, a 35% revenue drop on a specific date caused by a stockout of the top 3 products AND a paused campaign. This makes evaluation deterministic.

---

## 7. Memory Architecture

### Short-term (in-graph)

The LangGraph state object is the short-term memory. It carries the full conversation history (`messages`) and all intermediate findings within a single session. It persists across `interrupt()` checkpoints via the checkpoint store.

### Long-term (vector store)

**File**: `memory/long_term.py`

Two retrieval paths:

1. **Semantic search** (for `recall` tool): embed the user's scenario description, retrieve top-k similar past incidents by cosine similarity.

2. **Structured lookup** (for orchestrator context injection): query by intent type or date range to pull recent incidents of the same class.

The `LongTermMemory` class wraps the vector store client and exposes:
- `write_incident(record: IncidentRecord)`
- `search_similar(query: str, top_k: int) -> List[IncidentRecord]`
- `get_by_intent(intent: str, limit: int) -> List[IncidentRecord]`

Seed the vector store with 10–15 synthetic past incidents at startup for demo purposes.

---

## 8. HITL API

**File**: `api/hitl_api.py`

```
GET  /hitl/pending                    → lists all sessions awaiting approval
GET  /hitl/pending/{session_id}       → returns proposed actions for a session
POST /hitl/approve/{session_id}       → approves; graph resumes
POST /hitl/reject/{session_id}        → rejects; graph resumes with rejected status
POST /hitl/modify/{session_id}        → approves with modifications to the action plan
```

This API is called by:
- The MCP server's `fix` tool (to check status)
- A web dashboard (optional)
- Claude Code / Copilot (when the MCP tool returns `awaiting_approval`)

In the MCP flow: the `fix` tool returns `awaiting_approval` + the proposed actions. The Claude Code agent surfaces this to the developer in the IDE. The developer types an approval command, which the Claude Code agent maps to a call to `POST /hitl/approve/{session_id}`. The MCP tool is called again with `resume: true` and the graph continues.

---

## 9. Observability

**File**: `observability/callbacks.py`

Add a `LangSmithCallbackHandler` to every LLM and tool call. Set these environment variables:

```
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=your_key
LANGCHAIN_PROJECT=ecommerce-ops-agent
```

This gives you a trace for every run in the LangSmith UI: which nodes were called, which tools fired, token counts, latency per node, and the full message history.

Additionally, instrument each node entry with a simple decorator that logs to stdout in structured JSON:

```python
{"event": "node_enter", "node": "orchestrator", "session_id": "...", "timestamp": "..."}
{"event": "tool_call", "tool": "get_revenue_timeseries", "input": {...}, "output": {...}}
{"event": "node_exit", "node": "orchestrator", "duration_ms": 1240}
```

This structured log is the primary signal for debugging and is easy to ship to any log aggregator (Datadog, CloudWatch, etc.) in production.

---

## 10. Evaluation

**Directory**: `eval/`

### Scenario-based evaluation

Define 15–20 test scenarios in `eval/test_scenarios.py`. Each scenario has:

```python
class EvalScenario(BaseModel):
    scenario_id: str
    query: str
    intent: str
    expected_root_causes: List[str]      # substring match is fine
    expected_specialists_called: List[str]
    expected_actions: Optional[List[str]]
    should_trigger_hitl: bool
    passing_conditions: List[str]        # free-text description for human eval
```

Cover all four intents and include at least 5 cross-domain scenarios (the ones that require correlating signals across two or more specialists).

### Unit tests

Test each node in isolation by constructing a partial state object and calling the node function directly. LangGraph nodes are plain Python functions — they're easy to unit test.

### LangSmith eval runner

Use `langsmith.evaluate()` with a custom evaluator that checks:
- Correct intent classification
- All expected specialists were called
- Root causes contain expected keywords
- HITL was triggered when expected
- Structured output schema is valid

---

## 11. Configuration

**File**: `config.py`

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # LLM
    anthropic_api_key: str
    model_name: str = "claude-sonnet-4-20250514"
    
    # LangSmith
    langchain_tracing_v2: bool = True
    langchain_api_key: str
    langchain_project: str = "ecommerce-ops-agent"
    
    # Checkpoint store
    checkpoint_backend: str = "memory"   # "memory" | "sqlite" | "postgres"
    postgres_url: Optional[str] = None
    
    # Vector store
    vector_backend: str = "chroma"       # "chroma" | "qdrant" | "pinecone"
    chroma_persist_dir: str = "./data/chroma"
    
    # HITL
    hitl_api_port: int = 8001
    hitl_timeout_seconds: int = 300
    
    # Agent
    reflection_confidence_threshold: float = 0.4
    max_reflection_retries: int = 2
    specialist_timeout_seconds: int = 30
    
    class Config:
        env_file = ".env"

settings = Settings()
```

---

## 12. Entry Point

**File**: `main.py`

Starts both the MCP server and the HITL FastAPI server in the same process using `asyncio`:

```python
import asyncio
from mcp_server.server import mcp_app
from api.hitl_api import hitl_app
import uvicorn

async def main():
    # Start HITL API in background
    config = uvicorn.Config(hitl_app, port=settings.hitl_api_port, log_level="info")
    server = uvicorn.Server(config)
    asyncio.create_task(server.serve())
    
    # Start MCP server (blocks)
    await mcp_app.run_async(transport="stdio")

if __name__ == "__main__":
    asyncio.run(main())
```

For Claude Code integration, add to `.mcp.json` in the project root:

```json
{
  "mcpServers": {
    "ecommerce-ops": {
      "command": "python",
      "args": ["main.py"],
      "cwd": "/path/to/ecommerce-ops-agent"
    }
  }
}
```

---

## 13. Implementation Order (Recommended)

Build in this sequence so you always have a runnable system:

1. **State + mock data** — define `OpsAgentState` and `MockDataStore` with a realistic scenario baked in.
2. **Tool layer** — implement all tools against mock data. Test each one directly.
3. **Single specialist** — build the sales specialist sub-graph end to end. Verify it calls tools and returns a `SpecialistFinding`.
4. **All four specialists** — replicate the pattern for inventory, marketing, support.
5. **Orchestrator + parallel dispatch** — wire `Send()` to fan out to specialists. Verify parallel execution.
6. **Aggregator** — implement cross-domain correlation. Test on a known scenario.
7. **Reflection** — add the gap detection loop. Verify it triggers on weak findings.
8. **Long-term memory** — implement vector store write and retrieval. Seed with synthetic incidents.
9. **HITL checkpoint** — add `interrupt()`, implement the FastAPI HITL endpoints. Test the full approve/reject cycle.
10. **Output formatter** — enforce Pydantic structured output on every exit path.
11. **MCP server** — wrap the graph with FastMCP. Test with Claude Code.
12. **Observability** — add LangSmith tracing throughout.
13. **Evaluation** — write and run the eval suite.

---

## 14. Scalability Notes

These are the exact points to mention in documentation, presentations, or a future production upgrade:

| What | Current approach | Production upgrade |
|---|---|---|
| Parallel specialist execution | `Send()` in-process async threads | LangGraph Cloud workers or Celery + Redis queue |
| Checkpoint persistence | `MemorySaver` (in-memory, lost on restart) | `AsyncPostgresSaver` with Postgres |
| Vector store | Chroma local file | Qdrant self-hosted or Pinecone managed |
| MCP transport | stdio (single client) | SSE or HTTP with auth (multiple clients) |
| Tool APIs | Mock Python functions | Real HTTP clients; same `@tool` interface |
| HITL surface | REST polling | WebSocket push or Server-Sent Events |
| LLM calls | Sequential within node | Batch with `langchain_core.runnables.RunnableBatch` |
| Multi-tenancy | Single session | Namespace vector store + checkpoint store by tenant_id |
| Secrets | `.env` file | HashiCorp Vault or AWS Secrets Manager |
| Deployment | Local process | Docker + Kubernetes; MCP server as a sidecar |
