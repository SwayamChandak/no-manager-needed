# E-Commerce AI Ops Agent — Project Plan

## Overview

An AI system that operates an online store like a smart operations manager. Business users ask natural language questions ("Why did sales drop yesterday?"), and the system investigates signals across multiple domains, explains what happened, recommends next steps, and executes corrective actions only after human approval.

---

## Technology Stack

| Concern | Choice |
|---|---|
| Agent framework | `langgraph` (StateGraph, Send, interrupt) |
| LLM | Azure GPT via `langchain-openai` (`AzureChatOpenAI`) |
| Tool definitions | `langchain-core` `@tool` decorator |
| MCP server | `fastmcp` (Python) |
| MCP transport | stdio (local), SSE (production) |
| Checkpoint store | `MemorySaver` (dev) → `AsyncPostgresSaver` (prod) |
| Long-term memory | **Qdrant** (vector store) |
| Embeddings | `langchain-openai` `AzureOpenAIEmbeddings` |
| Structured output | Pydantic v2 models |
| Observability | LangSmith |
| HITL API | `fastapi` + `uvicorn` |
| Config | `pydantic-settings`, `.env` |

---

## Repository Structure

```
ecommerce-ops-agent/
├── mcp_server/
│   ├── server.py              # FastMCP server — entry point for all MCP clients
│   ├── tools.py               # MCP tool definitions (diagnose, fix, recall, summarize)
│   └── schemas.py             # Pydantic models for MCP tool inputs/outputs
│
├── agent/
│   ├── graph.py               # LangGraph StateGraph — master graph topology
│   ├── state.py               # OpsAgentState TypedDict
│   ├── orchestrator.py        # Intent parsing, routing, synthesis
│   ├── aggregator.py          # Cross-domain correlation and root cause ranking
│   ├── reflection.py          # Gap detection and re-routing logic
│   ├── hitl.py                # interrupt() primitive and checkpoint resume
│   └── specialists/
│       ├── sales.py           # Sales specialist sub-graph
│       ├── inventory.py       # Inventory specialist sub-graph
│       ├── marketing.py       # Marketing specialist sub-graph
│       └── support.py         # Support specialist sub-graph
│
├── tools/
│   ├── analytics.py           # Sales/revenue tools
│   ├── inventory.py           # Stock level tools
│   ├── crm.py                 # Complaints, refunds, reviews tools
│   ├── campaigns.py           # Campaign performance tools
│   └── actions.py             # Action executor tools (restock, discount, pause, ticket)
│
├── memory/
│   ├── short_term.py          # LangGraph state helpers
│   ├── long_term.py           # Qdrant read/write, episode management
│   └── schemas.py             # IncidentRecord Pydantic model
│
├── api/
│   └── hitl_api.py            # FastAPI: /approve, /reject, /pending, /modify
│
├── observability/
│   └── callbacks.py           # LangSmith callback handler, structured JSON logging
│
├── eval/
│   ├── test_scenarios.py      # 15–20 evaluation scenarios
│   ├── test_graph.py          # Unit tests per node
│   └── eval_runner.py         # LangSmith eval runner
│
├── config.py                  # Pydantic settings, env var loading
└── main.py                    # Starts MCP server + HITL FastAPI together
```

---

## System Architecture

### Two-Layer Design

**Outer layer** — FastMCP server: exposes 4 tools to any MCP-compatible client. Does no reasoning. Pure adapter.

**Inner layer** — LangGraph graph: all intelligence lives here. Orchestrates specialists, aggregates findings, reflects, handles HITL, writes memory.

### Graph Flow

```
[START]
  → orchestrator
  → [parallel via Send()] → sales_agent, inventory_agent, marketing_agent, support_agent
  → aggregator
  → reflection                  ← loops back to orchestrator if gaps detected (max 2 retries)
  → hitl_checkpoint             ← suspends here for fix intent; passes through for others
  → action_executor             ← only after human approval
  → memory_writer
  → output_formatter
[END]
```

**Conditional edges:**
- After `reflection`: gaps found → back to `orchestrator`. Passed → `hitl_checkpoint`.
- After `hitl_checkpoint`: `diagnose` / `recall` / `summarize` → `output_formatter`. `fix` → `action_executor`.
- After `action_executor`: always → `memory_writer`.

---

## How Cross-Domain Queries Work

This is the most important architectural point.

**Parallel fan-out = speed, not cross-domain reasoning.**

Each specialist works independently and calls only its own domain's tools. Specialists never communicate with each other. LangGraph collects all `Send()` outputs back into shared state before the next node runs.

**The Aggregator is where cross-domain intelligence happens.** It receives all 4 `SpecialistFinding` objects simultaneously and runs a single LLM call:

> *"Sales dropped 35% at 14:00. Inventory shows Laptop Pro went out of stock at 13:45. Marketing shows a campaign was paused at 13:30. Are these causally linked?"*

It outputs:
1. A **correlation matrix** — pairwise causal analysis across domains
2. **Ranked root causes** — each with confidence score, supporting domains, and evidence
3. **Proposed actions** — derived from findings, typed and justified

---

## MCP Tools (4 only)

| Tool | Intent | Mutates State? | Description |
|---|---|---|---|
| `diagnose` | Root cause analysis | No | Full parallel specialist run, cross-domain correlation, explanation |
| `fix` | Corrective action | Yes (after approval) | Proposes actions, pauses for HITL, executes on approval |
| `recall` | Memory retrieval | No | Pure Qdrant vector search — does not invoke the graph |
| `summarize` | Executive summary | No | Pulls from all 4 domains, returns health score and top issues |

---

## Schemas (Phase 1 — All Pydantic v2)

### Graph State
```python
class OpsAgentState(TypedDict):
    session_id: str
    user_query: str
    intent: str                    # "diagnose" | "fix" | "recall" | "summarize"
    active_specialists: List[str]
    retry_count: int
    sales_findings: Optional[SpecialistFinding]
    inventory_findings: Optional[SpecialistFinding]
    marketing_findings: Optional[SpecialistFinding]
    support_findings: Optional[SpecialistFinding]
    root_causes: List[RootCause]
    correlation_matrix: Dict
    reflection_notes: List[str]
    reflection_passed: bool
    proposed_actions: List[ProposedAction]
    approved_actions: List[ProposedAction]
    executed_actions: List[ExecutedAction]
    retrieved_memories: List[PastIncident]
    final_response: Optional[StructuredResponse]
    messages: List[BaseMessage]
    tool_call_log: List[Dict]
    timestamp: str
```

### Domain Models
- `SpecialistFinding` — domain, signals found, confidence, raw tool outputs
- `RootCause` — description, confidence (0.0–1.0), supporting domains, evidence
- `OrchestratorDecision` — intent, active_specialists, sub_questions per specialist (structured LLM output)
- `ProposedAction` — type, parameters, justification, estimated impact
- `ExecutedAction` — action, status, timestamp, API response
- `AggregatorOutput` — correlation_matrix, root_causes, proposed_actions
- `StructuredResponse` — final user-facing output

### Memory Model
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
    embedding_text: str   # query + root_causes + actions, used for vector search
```

### MCP Output Schemas
- `DiagnoseResult` — finding, root_causes, confidence, supporting_data, recommended_actions
- `FixResult` — status (`awaiting_approval` | `executed` | `rejected`), actions_taken, summary
- `RecallResult` — incidents: List[PastIncident], summary
- `SummaryResult` — executive_summary, health_score, top_issues, recommended_actions

---

## Tool Layer Design

No shared mock data file. Each tool returns a hardcoded dict directly as a placeholder. Real API logic is added later without changing the tool's name or schema.

```python
@tool
def get_revenue_timeseries(date: str, granularity: str = "hourly") -> dict:
    """
    Returns revenue timeseries for a given date.
    date: ISO date string (e.g. '2025-01-15')
    granularity: 'hourly' or 'daily'
    Returns: { "date": str, "total": float, "data_points": [...] }
    """
    # Placeholder — replace with real API call
    return {
        "date": date,
        "total": 12400.0,
        "data_points": [{"time": "09:00", "revenue": 3200.0}]
    }
```

### Tools per Specialist

| Specialist | Tools |
|---|---|
| Sales | `get_revenue_timeseries`, `get_order_volume`, `get_revenue_by_product`, `get_revenue_by_region`, `detect_anomaly` |
| Inventory | `get_stock_levels`, `get_stockout_events`, `get_viewed_not_purchased`, `get_restock_recommendations` |
| Marketing | `get_campaign_performance`, `get_channel_breakdown`, `get_paused_campaigns`, `get_promotion_schedule` |
| Support | `get_complaint_volume`, `get_refund_rate`, `get_review_sentiment`, `get_common_issues` |
| Actions | `restock_product`, `apply_discount`, `pause_campaign`, `create_support_ticket` |

---

## Specialist Agent Pattern

Each specialist is a compiled LangGraph subgraph:

```
[START] → analyst_node → [tool loop via ToolNode] → summarizer_node → [END]
```

- `analyst_node`: ReAct-style LLM, calls domain tools in a loop
- `summarizer_node`: formats raw results into a `SpecialistFinding`

Each specialist only has access to its own domain's tools.

---

## Memory Architecture

### Short-term
LangGraph state object. Carries full message history and all intermediate findings within a session. Persists across `interrupt()` checkpoints.

### Long-term (Qdrant)
`LongTermMemory` class exposes:
- `write_incident(record: IncidentRecord)` — embeds `embedding_text` and stores
- `search_similar(query: str, top_k: int) -> List[IncidentRecord]` — cosine similarity search
- `get_by_intent(intent: str, limit: int) -> List[IncidentRecord]` — structured filter

Two retrieval paths:
1. **Semantic search** — for the `recall` MCP tool
2. **Context injection** — orchestrator pulls recent similar incidents before routing

Seed with 10–15 synthetic past incidents at startup for demo.

---

## HITL Flow

1. `fix` intent reaches `hitl_checkpoint` node
2. Node calls `interrupt({"proposed_actions": [...]})` — graph suspends
3. MCP `fix` tool returns `status: "awaiting_approval"` to client
4. Human approves/rejects via FastAPI endpoint or IDE command
5. Graph resumes: `POST /hitl/approve/{session_id}` → `action_executor` runs
6. Graph resumes: `POST /hitl/reject/{session_id}` → routes to output, no mutations

### HITL API Endpoints
```
GET  /hitl/pending
GET  /hitl/pending/{session_id}
POST /hitl/approve/{session_id}
POST /hitl/reject/{session_id}
POST /hitl/modify/{session_id}
```

---

## Configuration

```python
class Settings(BaseSettings):
    # Azure OpenAI
    azure_openai_api_key: str
    azure_openai_endpoint: str
    azure_openai_deployment: str
    azure_openai_api_version: str = "2024-02-01"

    # Embeddings
    azure_embedding_deployment: str

    # LangSmith
    langchain_tracing_v2: bool = True
    langchain_api_key: str
    langchain_project: str = "ecommerce-ops-agent"

    # Qdrant
    qdrant_url: str
    qdrant_api_key: Optional[str] = None
    qdrant_collection: str = "incident_memory"

    # Checkpoint store
    checkpoint_backend: str = "memory"   # "memory" | "sqlite" | "postgres"
    postgres_url: Optional[str] = None

    # HITL
    hitl_api_port: int = 8001
    hitl_timeout_seconds: int = 300

    # Agent
    reflection_confidence_threshold: float = 0.4
    max_reflection_retries: int = 2
    specialist_timeout_seconds: int = 30

    class Config:
        env_file = ".env"
```

---

## Build Phases & Agent Assignments

| Phase | What Gets Built | Agent | Files |
|---|---|---|---|
| **1 — Schemas** | All Pydantic models, TypedDicts, state definition | `state_schema` | `agent/state.py`, `memory/schemas.py`, `mcp_server/schemas.py` |
| **2 — Graph topology** | StateGraph wiring, edges, `Send()`, subgraph registration | `graph_architect` | `agent/graph.py` |
| **3 — Node logic + tools** | Orchestrator, all 4 specialists, aggregator, reflection, HITL, action executor, output formatter, all `@tool` stubs | `node_logic` | `agent/orchestrator.py`, `agent/specialists/*.py`, `agent/aggregator.py`, `agent/reflection.py`, `agent/hitl.py`, `tools/*.py` |
| **4 — Memory** | `LongTermMemory` (Qdrant), `memory_writer_node`, seed data | `memory` | `memory/long_term.py`, `memory/short_term.py` |
| **5 — MCP + HITL API** | FastMCP server, 4 MCP tools, FastAPI HITL endpoints, `main.py`, `.mcp.json` | `mcp_tool` | `mcp_server/server.py`, `mcp_server/tools.py`, `api/hitl_api.py`, `main.py` |

---

## Build Sequence (within phases, sequential)

1. `OpsAgentState` + all Pydantic models
2. All `@tool` stubs (placeholder return dicts)
3. Sales specialist subgraph end-to-end
4. Remaining 3 specialists (same pattern)
5. Orchestrator + `Send()` parallel dispatch
6. Aggregator (cross-domain correlation)
7. Reflection (gap detection loop)
8. Long-term memory (Qdrant write + retrieval)
9. HITL checkpoint + FastAPI endpoints
10. Output formatter (structured Pydantic output on all exit paths)
11. FastMCP server wrapper
12. LangSmith observability
13. Evaluation suite

---

## Observability

- LangSmith tracing on every LLM call and tool call
- Structured JSON logs per node:
  ```json
  {"event": "node_enter", "node": "orchestrator", "session_id": "...", "timestamp": "..."}
  {"event": "tool_call", "tool": "get_revenue_timeseries", "input": {}, "output": {}}
  {"event": "node_exit", "node": "orchestrator", "duration_ms": 1240}
  ```

---

## Evaluation

Each scenario:
```python
class EvalScenario(BaseModel):
    scenario_id: str
    query: str
    intent: str
    expected_root_causes: List[str]
    expected_specialists_called: List[str]
    expected_actions: Optional[List[str]]
    should_trigger_hitl: bool
    passing_conditions: List[str]
```

Coverage: all 4 intents, minimum 5 cross-domain scenarios requiring correlation across 2+ specialists.

---

## Database Schema (PostgreSQL)

PostgreSQL serves as the relational backbone of the ops agent. It handles four distinct concerns: LangGraph graph state checkpointing (so sessions can be suspended at `interrupt()` and resumed across process restarts), HITL request lifecycle tracking (recording what was proposed, who approved it, and when), structured incident history that is queryable and filterable by intent, date, and outcome (complementing the semantic search Qdrant provides), and a full audit trail of every action executed against external APIs. Qdrant owns vector storage and semantic similarity; PostgreSQL owns everything relational.

PostgreSQL will be run via Docker Compose on `localhost:5432`, database name `ops_agent`.

### Schema Overview

| Table | Primary Key | Purpose | FKs to |
|---|---|---|---|
| `sessions` | `session_id` UUID | Core record for every agent invocation | — |
| `specialist_findings` | `id` UUID | One row per specialist per session | `sessions` |
| `root_causes` | `id` UUID | Aggregator-ranked root causes per session | `sessions` |
| `hitl_requests` | `id` UUID | HITL lifecycle tracking — one per fix run | `sessions` |
| `executed_actions` | `id` UUID | Audit trail of every action executed | `sessions`, `hitl_requests` |
| `incidents` | `incident_id` UUID | Structured incident history written after every completed run | `sessions` (nullable) |

### DDL

```sql
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. sessions
--    One row per agent invocation. All specialist findings and actions
--    reference this table. LangGraph checkpoint tables (managed separately)
--    use the same session_id as their thread_id.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE sessions (
    session_id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_query          TEXT        NOT NULL,
    intent              VARCHAR(20) NOT NULL
                            CHECK (intent IN ('diagnose', 'fix', 'recall', 'summarize')),
    status              VARCHAR(20) NOT NULL DEFAULT 'running'
                            CHECK (status IN ('running', 'completed', 'failed', 'awaiting_approval')),
    active_specialists  JSONB,                        -- e.g. ["sales", "inventory"]
    retry_count         SMALLINT    DEFAULT 0,
    reflection_passed   BOOLEAN,
    reflection_notes    JSONB,                        -- array of gap description strings
    correlation_matrix  JSONB,                        -- {"domain_a-domain_b": {"linked": bool, ...}}
    final_response      JSONB,                        -- serialised StructuredResponse; NULL until complete
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    completed_at        TIMESTAMPTZ                   -- NULL while running
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. specialist_findings
--    One row per (session, domain) pair. UNIQUE constraint enforces that each
--    specialist writes at most one finding per session.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE specialist_findings (
    id                    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id            UUID        NOT NULL
                              REFERENCES sessions(session_id) ON DELETE CASCADE,
    domain                VARCHAR(20) NOT NULL
                              CHECK (domain IN ('sales', 'inventory', 'marketing', 'support')),
    signals               JSONB       NOT NULL,   -- array of observation strings
    confidence            FLOAT       NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    raw_tool_outputs      JSONB,                  -- array of {tool_name, output} dicts
    sub_question_answered TEXT,
    created_at            TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (session_id, domain)
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 3. root_causes
--    One or more rows per session, ordered by rank (1 = primary cause).
--    Written by the aggregator node.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE root_causes (
    id                 UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id         UUID        NOT NULL
                           REFERENCES sessions(session_id) ON DELETE CASCADE,
    description        TEXT        NOT NULL,
    confidence         FLOAT       NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    supporting_domains JSONB       NOT NULL,  -- e.g. ["sales", "inventory"]
    evidence           JSONB       NOT NULL,  -- array of specific data-point strings
    rank               SMALLINT,              -- 1 = highest-confidence root cause
    created_at         TIMESTAMPTZ DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 4. hitl_requests
--    Exactly one row per session that reaches the hitl_checkpoint node.
--    UNIQUE on session_id enforces the one-HITL-per-session invariant.
--    resolved_at is set when a human approves, rejects, modifies, or the
--    request times out.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE hitl_requests (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id       UUID        NOT NULL UNIQUE
                         REFERENCES sessions(session_id) ON DELETE CASCADE,
    status           VARCHAR(20) NOT NULL DEFAULT 'pending'
                         CHECK (status IN ('pending', 'approved', 'rejected', 'modified', 'timed_out')),
    proposed_actions JSONB       NOT NULL,  -- array of serialised ProposedAction objects
    approved_actions JSONB,                 -- NULL until resolved; may differ from proposed_actions if modified
    reviewer_note    TEXT,                  -- optional free-text from the human reviewer
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    resolved_at      TIMESTAMPTZ            -- NULL while pending
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 5. executed_actions
--    One row per action executed by action_executor. hitl_request_id is
--    nullable because recall/summarize/diagnose runs do not go through HITL
--    yet may still log informational actions.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE executed_actions (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID        NOT NULL
                        REFERENCES sessions(session_id) ON DELETE CASCADE,
    hitl_request_id UUID
                        REFERENCES hitl_requests(id) ON DELETE SET NULL,
    action_type     VARCHAR(30) NOT NULL
                        CHECK (action_type IN ('restock', 'apply_discount', 'pause_campaign', 'create_ticket')),
    parameters      JSONB       NOT NULL,
    status          VARCHAR(10) NOT NULL CHECK (status IN ('success', 'failed')),
    api_response    JSONB,                  -- raw response from the external API; NULL on failure
    executed_at     TIMESTAMPTZ DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 6. incidents
--    Written by memory_writer_node after every completed run. session_id is
--    nullable (ON DELETE SET NULL) so incident records survive even if the
--    parent session row is purged. qdrant_point_id cross-references the vector
--    stored in Qdrant for the same incident.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE incidents (
    incident_id      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id       UUID
                         REFERENCES sessions(session_id) ON DELETE SET NULL,
    query            TEXT        NOT NULL,
    intent           VARCHAR(20) NOT NULL,
    root_causes      JSONB       NOT NULL,  -- array of string summaries (not full RootCause objects)
    actions_proposed JSONB       NOT NULL,  -- array of strings
    actions_approved JSONB       NOT NULL,  -- array of strings
    actions_executed JSONB       NOT NULL,  -- array of strings
    outcome_summary  TEXT        NOT NULL,
    embedding_text   TEXT        NOT NULL,  -- text that was embedded and stored in Qdrant
    qdrant_point_id  UUID,                  -- reference to the Qdrant vector point; NULL if not yet embedded
    created_at       TIMESTAMPTZ DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Indexes
-- ─────────────────────────────────────────────────────────────────────────────

-- sessions: frequent filter axes
CREATE INDEX idx_sessions_intent      ON sessions(intent);
CREATE INDEX idx_sessions_status      ON sessions(status);
CREATE INDEX idx_sessions_created_at  ON sessions(created_at);

-- child tables: FK join paths
CREATE INDEX idx_specialist_findings_session_id ON specialist_findings(session_id);
CREATE INDEX idx_root_causes_session_id         ON root_causes(session_id);

-- incidents: query and recall filter axes
CREATE INDEX idx_incidents_intent       ON incidents(intent);
CREATE INDEX idx_incidents_created_at   ON incidents(created_at);
CREATE INDEX idx_incidents_qdrant_point ON incidents(qdrant_point_id);
```

### LangGraph Checkpoint Tables (Auto-Managed)

The following three tables are created automatically by `AsyncPostgresSaver.from_conn_string()` and must **not** be managed manually — do not add them to the DDL above or run migrations against them:

- **`checkpoints`** — Full snapshots of `OpsAgentState` keyed by `(thread_id, checkpoint_id)`. `thread_id` maps 1-to-1 with `session_id`. Enables session resume after `interrupt()`.
- **`checkpoint_blobs`** — Binary storage for large or binary state fields that exceed the inline JSON limit.
- **`checkpoint_writes`** — Pending write buffer recording in-progress node outputs before they are promoted to a full checkpoint snapshot.

These tables are populated by the LangGraph runtime whenever the graph calls `checkpointer.put(...)`. No application code should `INSERT` or `UPDATE` them directly.

### Environment Variables

The following variables must be added to `config.py` / `.env` when PostgreSQL integration begins:

| Variable | Default | Description |
|---|---|---|
| `POSTGRES_HOST` | `localhost` | Hostname of the PostgreSQL server |
| `POSTGRES_PORT` | `5432` | Port |
| `POSTGRES_DB` | `ops_agent` | Database name |
| `POSTGRES_USER` | _(required)_ | Database user |
| `POSTGRES_PASSWORD` | _(required)_ | Database password |
| `DATABASE_URL` | _(required)_ | Full DSN — `postgresql+asyncpg://user:password@host:port/db` — used by both `AsyncPostgresSaver` and direct `asyncpg` connections |

---

## Business Questions the System Must Handle

### Sales & Revenue
- "Why did sales drop yesterday?"
- "Compare yesterday's sales with last week."
- "Which products contributed most to the revenue drop?"
- "Was the drop due to fewer orders or lower order value?"
- "Did any region perform worse than usual?"
- "Is this drop normal or an anomaly?"

### Inventory & Supply
- "Were any top-selling products out of stock yesterday?"
- "Which products are close to stock-out?"
- "Did inventory issues impact conversions?"
- "Should we restock any product immediately?"

### Marketing & Campaigns
- "Were any campaigns paused or underperforming?"
- "Did campaign performance drop compared to last week?"
- "Which channel performed the worst yesterday?"
- "Should we run a discount to recover sales?"

### Customer Support
- "Did customer complaints increase yesterday?"
- "Are refunds or returns higher than usual?"
- "Is there a common issue reported by customers?"

### Cross-Domain Root Cause
- "Was the sales drop caused by inventory, marketing, or customer issues?"
- "Correlate complaints with sales drop."
- "Did out-of-stock items also have active campaigns?"
- "Show me all contributing factors for yesterday's drop."

### Memory-Based
- "Has this happened before?"
- "What did we do last time sales dropped like this?"
- "Did discounts help previously?"
- "Which actions worked best in past incidents?"

### Action-Oriented (HITL required)
- "Fix the issue."
- "Restock affected products."
- "Run a 10% discount on top 3 products."
- "Pause the worst-performing campaign."
- "Create a support ticket for this issue."

### Reporting
- "Summarize yesterday's business health."
- "Create an executive summary of the issue."
- "What actions do you recommend and why?"
