# Low-Level Design (LLD) — E-Commerce AI Ops Agent

---

## 1. System Purpose (One-liner for each audience)

**Technical:** A multi-agent LangGraph system that receives natural-language business questions via an MCP interface, fans them out to domain-specialist ReAct agents backed by a real PostgreSQL database, cross-correlates findings using an LLM aggregator, applies a reflection loop for quality control, suspends for human approval before executing write actions, and writes episodic memory to Qdrant for future recall.

**Non-technical:** Think of it as a team of AI department managers (Sales, Inventory, Marketing, Support) that you can chat with like a person. You ask "why did sales drop?", each manager investigates their area, they meet and agree on a root cause, and only after a human gives the green light does the system actually do anything (like restocking products or pausing an ad campaign). It also remembers every past investigation so it can learn from history.

---

## 2. Two-Layer Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     OUTER LAYER: MCP Server                      │
│                       (FastMCP — pure adapter)                   │
│    diagnose() │ fix() │ recall() │ summarize()  +  Prompts       │
└───────────────────────────┬─────────────────────────────────────┘
                            │  graph.ainvoke()
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                    INNER LAYER: LangGraph Graph                   │
│            (All intelligence, routing, memory, HITL)             │
└─────────────────────────────────────────────────────────────────┘
```

The MCP server contains **zero business logic**. Every call is a thin wrapper that builds initial state and calls `graph.ainvoke()`. This separation means the graph can be tested, swapped, or triggered by a Gradio UI without changing the MCP contract.

---

## 3. Full Graph Flow (with conditions)

```
[START]
   │
   ▼
┌──────────────────┐
│  orchestrator    │  ← Parses intent, selects specialists, forms sub-questions
│  (LLM call)      │    structured output → OrchestratorDecision
└──────┬───────────┘
       │ route_to_specialists() — Send() fan-out (parallel)
       ├──────────────┬──────────────┬──────────────┐
       ▼              ▼              ▼               ▼
  ┌─────────┐  ┌──────────┐  ┌──────────┐  ┌─────────────┐
  │  sales  │  │inventory │  │marketing │  │  support    │
  │  node   │  │  node    │  │  node    │  │   node      │
  │ ReAct   │  │ ReAct    │  │ ReAct    │  │  ReAct      │
  └────┬────┘  └────┬─────┘  └────┬─────┘  └──────┬──────┘
       └────────────┴──────────────┴────────────────┘
                            │  (barrier — all must finish)
                            ▼
                    ┌───────────────┐
                    │  aggregator   │  ← Cross-domain correlation matrix
                    │  (LLM call)   │    ranks root causes, proposes actions
                    └──────┬────────┘
                           │
                           ▼
                    ┌───────────────┐
                    │  reflection   │  ← Deterministic quality check (no LLM)
                    └──────┬────────┘
                           │
              ┌────────────┴──────────────────┐
              │ route_after_reflection()        │
              │                                 │
   passed=False AND retries<2       passed=True OR retries≥2
              │                                 │
              ▼                                 ▼
    orchestrator (retry)            ┌───────────────────┐
                                    │   hitl_node       │  ← interrupt() if intent="fix"
                                    └──────┬────────────┘
                                           │
                           ┌───────────────┴──────────────────┐
                           │  route_after_hitl()               │
                           │                                   │
                     intent="fix"                    intent≠"fix"
                           │                                   │
                           ▼                                   │
                  ┌─────────────────┐                         │
                  │ action_executor │                          │
                  │ (write tools)   │                          │
                  └──────┬──────────┘                         │
                         │                                     │
                         └──────────────┬──────────────────────┘
                                        ▼
                              ┌──────────────────┐
                              │  memory_writer   │  ← Writes IncidentRecord to Qdrant
                              └──────┬───────────┘
                                     ▼
                              ┌──────────────────┐
                              │ output_formatter │  ← LLM call → StructuredResponse
                              └──────┬───────────┘
                                     ▼
                                   [END]
```

---

## 4. Component-by-Component Breakdown

### 4.1 State — `agent/state.py`

The central data contract. All nodes read from and write to `OpsAgentState`. LangGraph merges state patches (dicts) returned by each node.

| Field | Type | Purpose |
|---|---|---|
| `session_id` | `str` | Thread ID for checkpointing |
| `user_query` | `str` | Raw user input |
| `intent` | `str` | `diagnose` / `fix` / `recall` / `summarize` |
| `active_specialists` | `List[str]` | Which specialist nodes to fan out to |
| `messages` | `Annotated[List[BaseMessage], add_messages]` | LangChain message history |
| `{domain}_findings` | `SpecialistFinding` | Per-domain output (signals, confidence, tool outputs) |
| `root_causes` | `List[RootCause]` | Ranked causes from aggregator |
| `correlation_matrix` | `CorrelationMatrix` | 6-pair cross-domain linkage |
| `proposed_actions` | `List[ProposedAction]` | Aggregator-generated actions |
| `approved_actions` | `List[ProposedAction]` | Post-HITL approved subset |
| `executed_actions` | `List[ExecutedAction]` | Results from action tools |
| `reflection_passed` | `bool` | Quality gate result |
| `reflection_notes` | `List[str]` | Reasons for failure |
| `retry_count` | `int` | Reflection loop counter |
| `retrieved_memories` | `List[PastIncident]` | From Qdrant recall |
| `final_response` | `StructuredResponse` | Final user-facing output |
| `tool_call_log` | `List[Dict]` | Audit trail from every node |

**Key design pattern:** `add_messages` reducer on the `messages` field means LangGraph automatically appends instead of overwriting — this is how fan-out specialists all write messages without race conditions.

---

### 4.2 Orchestrator — `agent/orchestrator.py`

**Role:** Brain of routing. First node to execute.

**Mechanism:**
- Uses `llm.with_structured_output(OrchestratorDecision)` — forces LLM to produce a validated Pydantic object.
- On first entry: parses intent from `user_query`, selects active specialists, generates targeted `SubQuestion` per specialist.
- On re-entry (reflection retry): receives `reflection_notes`, generates refined follow-up sub-questions.
- Writes specialist sub-questions as `HumanMessage` objects with tags like `[SALES_SUBQUESTION]` into `messages`.

**Structured Output (`OrchestratorDecision`):**
```
intent: "diagnose" | "fix" | "recall" | "summarize"
active_specialists: ["sales", "inventory", ...]
sub_questions: [SubQuestion(specialist, question)]
reasoning: str
```

---

### 4.3 Specialists — `agent/specialists/{sales,inventory,marketing,support}.py`

All four follow the identical pattern (ReAct loop per domain):

```
1. Extract sub-question from messages (looks for [DOMAIN_SUBQUESTION] tag)
2. Build create_react_agent(llm, domain_tools, system_prompt)
3. ainvoke() → ReAct loop (Thought → Tool → Observation → repeat)
4. Extract ToolMessages as raw_tool_outputs
5. Second LLM call: summarize findings into signals[] + confidence float
6. Return SpecialistFinding into state["{domain}_findings"]
```

**Each specialist's tools:**

| Specialist | Tools |
|---|---|
| Sales | `get_revenue_timeseries`, `get_order_volume`, `get_revenue_by_product`, `get_revenue_by_region`, `detect_anomaly` |
| Inventory | `get_stock_levels`, `get_low_stock_products`, `get_stockout_events`, `get_restock_orders` |
| Marketing | `get_campaign_performance`, `get_channel_attribution`, `get_top_performing_campaigns` |
| Support | `get_complaint_volume`, `get_refund_rate`, `get_top_complaints`, `get_nps_trend` |

**All tools are:** `@tool`-decorated async functions querying PostgreSQL via asyncpg pool.

---

### 4.4 Aggregator — `agent/aggregator.py`

**Role:** Cross-domain synthesis. Receives all 4 `SpecialistFinding` objects.

**Mechanism:** Single structured LLM call with `AggregatorOutput` as the output schema.

**Produces:**
- `CorrelationMatrix`: 6 pairwise domain comparisons (sales↔inventory, etc.), each with `linked: bool` and `explanation`
- `root_causes: List[RootCause]` — ranked by `confidence` (0.0–1.0), with `supporting_domains` and `evidence`
- `proposed_actions: List[ProposedAction]` — 1–3 concrete actions (`restock`, `apply_discount`, `pause_campaign`, `relaunch_campaign`, `launch_campaign`, `create_ticket`)
- `summary: str` — one-paragraph human-readable synthesis

---

### 4.5 Reflection — `agent/reflection.py`

**Role:** Deterministic quality gate. No LLM call.

**Four checks:**
1. Are there any root causes at all (for `diagnose`/`fix` intent)?
2. Are ALL root causes below the `reflection_confidence_threshold` (default `0.4`)?
3. Did `fix` intent produce at least one proposed action?
4. Did any active specialist return empty signals?

**Routing logic:**
- If checks fail AND `retry_count < max_reflection_retries` (default 2): returns `reflection_passed=False`, sends graph back to orchestrator with notes.
- If max retries reached: forces `reflection_passed=True` with a `[MAX RETRIES REACHED]` flag in notes.
- The conditional edge `route_after_reflection()` reads `reflection_passed` and `retry_count` to pick the next node.

---

### 4.6 HITL Node — `agent/hitl.py`

**Role:** Suspend graph execution for human approval before any write actions.

**Mechanism:**
- If `intent != "fix"`: returns `{}` (pass-through, no interruption).
- If `intent == "fix"`: calls `interrupt(payload)` where payload includes `proposed_actions`.
- LangGraph serializes the entire graph state into the checkpoint store at this point.
- The graph is **suspended** — no Python thread is blocked. The checkpoint holds state.
- Human calls `/hitl/approve/{session_id}` on the FastAPI server.
- FastAPI calls `graph.astream(Command(resume=approval_payload), config)`.
- `interrupt()` returns the `approval_payload` dict.
- `approved_actions` is populated (or empty if rejected).

---

### 4.7 Action Executor — `agent/action_executor.py`

**Role:** Execute approved write operations against the database.

**Mechanism:**
- Iterates `approved_actions` list.
- Looks up `ACTION_TOOL_MAP` (dict mapping `action_type → async @tool function`).
- Calls `await tool_fn.ainvoke(params)` where params are parsed from the JSON string stored in `ProposedAction.parameters`.
- Uses a `ContextVar` (`current_session_id`) so tools can record which session triggered the action without changing signatures.
- Returns `List[ExecutedAction]` with `status: "success" | "failed"` and the API response.

---

### 4.8 Memory — `memory/`

**Short-term** (`short_term.py`): LangGraph's built-in state. Lives in `OpsAgentState`. Cleared per session.

**Long-term** (`long_term.py`): Qdrant vector store.

| Operation | When | What |
|---|---|---|
| `write_incident()` | After every completed graph run (memory_writer node) | Embeds `IncidentRecord.embedding_text` and upserts to Qdrant |
| `search_similar()` | recall intent | Cosine similarity search, returns top-k `IncidentRecord` |
| `get_by_intent()` | by intent filter | Qdrant scroll with filter |

**Embeddings:** HuggingFace `BAAI/bge-small-en-v1.5` (384-dim, runs on CPU). Chosen to avoid Azure API calls for every embedding operation.

**`IncidentRecord` schema:**
```
incident_id, timestamp, query, intent,
root_causes[], actions_proposed[], actions_approved[], actions_executed[],
outcome_summary, embedding_text (query + causes + actions concatenated)
```

---

### 4.9 MCP Server — `mcp_server/`

**`server.py`:** Creates `FastMCP` instance, registers 4 tools + 5 pre-built prompts. Supports `stdio` transport (Claude Code, GitHub Copilot) and `SSE` (web clients).

**`mcp_tools.py`:** The 4 tool implementations:
- `diagnose(question, session_id)` → runs full read-only graph → `DiagnoseResult`
- `fix(question, session_id)` → runs graph until HITL suspend → `FixResult` with `requires_approval=True`
- `recall(query, session_id)` → hits Qdrant directly + runs graph → `RecallResult`
- `summarize(session_id)` → runs graph with `summarize` intent → `SummaryResult`

**`schemas.py`:** Pydantic output models (`DiagnoseResult`, `FixResult`, `RecallResult`, `SummaryResult`) — the MCP wire format.

---

### 4.10 HITL API — `api/hitl_api.py`

FastAPI server running on port 8001. Endpoints:

| Endpoint | Method | Purpose |
|---|---|---|
| `/hitl/pending` | GET | List all suspended session IDs |
| `/hitl/pending/{session_id}` | GET | Get proposed actions for a session |
| `/hitl/approve/{session_id}` | POST | Approve (all or modified subset) → `Command(resume={approved:True, modified_actions})` |
| `/hitl/reject/{session_id}` | POST | Reject → `Command(resume={approved:False})` |

Reads live state via `graph.get_state(config)`. Resumes via `graph.astream(Command(resume=payload), config)`.

---

### 4.11 Database — `db/`

**Engine:** PostgreSQL via asyncpg (async, connection pooled).

**Schemas:**
- `public` — base schema (users, sessions)
- `store` — business schema (`products`, `orders`, `inventory_events`, `promotions`, `campaigns`, `support_tickets`, `restock_orders`)

**Connection pattern:** Module-level `_pool` singleton. `configure(dsn)` called at startup (sync). `db_connection()` is an async context manager that lazy-initializes the pool on first use.

---

### 4.12 Observability & Eval — `observability/` + `eval/`

**LangSmith:** Tracing enabled via env vars. Every node's LLM call is traced.

**DeepEval:** Each LLM-calling node is decorated with `@observe(metrics=[...])`. Metrics:
- `AnswerRelevancyMetric` — is the output relevant to the question?
- `FaithfulnessMetric` — is output grounded in retrieved tool data? (specialist nodes)
- `TaskCompletionMetric` — did the agent complete its assigned task?
- `GEval` — custom domain-specific rubrics (routing correctness, root cause quality, response clarity)

Judge model: Azure GPT (same deployment) with a threshold of `0.6`.

---

### 4.13 Configuration — `config.py`

`pydantic-settings` `BaseSettings` class. Reads from `.env`. Key settings:

| Setting | Default | Meaning |
|---|---|---|
| `reflection_confidence_threshold` | `0.4` | Minimum acceptable confidence for root causes |
| `max_reflection_retries` | `2` | Max reflection loops before forcing pass |
| `checkpoint_backend` | `"memory"` | `MemorySaver` in dev, `AsyncPostgresSaver` in prod |
| `hitl_timeout_seconds` | `300` | How long HITL interrupt waits |
| `qdrant_collection` | `"incident_memory"` | Qdrant collection name |

---

### 4.14 Entry Points — `main.py` + `ui/chatbot.py`

**`--mode mcp` (default):** FastMCP stdio server (foreground) + FastAPI HITL (background daemon thread). Used by Claude Code / GitHub Copilot via `.mcp.json`.

**`--mode chat`:** Gradio chatbot UI on port 7860 (foreground) + HITL FastAPI (background). The UI streams graph node events in real-time and renders a live HITL approval panel with checkboxes when the graph suspends.

---

## 5. Data Flow for a "diagnose" Query

```
User: "Why did sales drop yesterday?"

1.  MCP client calls diagnose("Why did sales drop yesterday?", session_id)
2.  mcp_tools.diagnose() builds OpsAgentState, calls graph.ainvoke()
3.  orchestrator: LLM → intent="diagnose", active_specialists=["sales","inventory","marketing","support"]
                  sub_questions: [{sales: "What is the revenue trend yesterday?"}, ...]
4.  Send() fan-out: 4 specialist nodes run in parallel
    - sales_node: ReAct agent queries get_revenue_timeseries("2026-06-09"), detect_anomaly()
    - inventory_node: ReAct queries get_stockout_events(), get_low_stock_products()
    - marketing_node: ReAct queries get_campaign_performance(), get_channel_attribution()
    - support_node: ReAct queries get_complaint_volume(), get_refund_rate()
5.  aggregator: LLM correlates all 4 findings → root_causes ranked, CorrelationMatrix built
6.  reflection: checks confidence > 0.4, signals non-empty → passes (or retries up to 2x)
7.  hitl_node: intent ≠ "fix" → pass-through, no interrupt
8.  route_after_hitl() → output_formatter_node (skips action_executor)
9.  memory_writer: writes IncidentRecord to Qdrant
10. output_formatter: LLM composes StructuredResponse from all state data
11. DiagnoseResult returned to MCP client
```

---

## 6. Data Flow for a "fix" Query

```
User: "Fix the stockout on SKU-123"

Steps 1–6: same as diagnose (intent="fix", aggregator proposes restock action)
7.  hitl_node: intent="fix" → interrupt({"proposed_actions": [...]})
    Graph is SUSPENDED. Checkpoint written to MemorySaver.
8.  MCP client returns FixResult(requires_approval=True, session_id)
9.  Human calls GET /hitl/pending/session_id (sees proposed restock)
10. Human calls POST /hitl/approve/session_id (with optional modifications)
11. FastAPI calls graph.astream(Command(resume={"approved": True}), config)
12. interrupt() returns approval payload inside hitl_node
13. approved_actions = proposed_actions (or modified subset)
14. action_executor: calls restock_product(product_id="SKU-123", quantity=50) via asyncpg
    → INSERT into store.restock_orders
15. memory_writer + output_formatter → final response with execution receipt
```

---

## 7. Security Patterns

- SQL injection prevention: parameterized queries (`$1`, `$2`) everywhere. Allowlist for `DATE_TRUNC` unit (never interpolates user input).
- Action parameter validation: `ProposedAction.parameters` is a JSON string, parsed with `json.loads()` — never `eval()`.
- `ContextVar` for session ID propagation: avoids parameter pollution across async boundaries.
- HITL as a mandatory gate: no write tool can be called without going through `hitl_node → action_executor` path (enforced by graph topology).

---

## 8. Dependency Map

```
main.py
 ├── mcp_server/server.py → mcp_server/mcp_tools.py → agent/graph.py
 ├── api/hitl_api.py → agent/graph.py (get_state, astream)
 └── ui/chatbot.py → agent/graph.py (astream_events)

agent/graph.py
 ├── agent/orchestrator.py → agent/state.py, eval/deepeval_setup.py
 ├── agent/specialists/*.py → tools/{analytics,inventory,campaigns,crm}.py → db/connection.py
 ├── agent/aggregator.py → agent/state.py
 ├── agent/reflection.py → agent/state.py, config.py
 ├── agent/hitl.py → langgraph.types.interrupt
 ├── agent/action_executor.py → tools/actions.py → db/connection.py
 ├── memory/long_term.py → qdrant_client, langchain_huggingface
 └── agent/output_formatter.py → agent/state.py
```

---

---

# Study Guide for the Review

---

## Section A: Core Concepts to Explain (Technical Audience)

### Architecture & Design
- **Two-layer separation** (MCP adapter vs LangGraph intelligence) — why is this the right design?
- **StateGraph vs MessageGraph** — what's the difference, why StateGraph was chosen
- **Why `TypedDict` for state** — type safety, JSON-serializable for checkpointing
- **`add_messages` reducer** — how it enables parallel writes without overwriting
- **`Send()` for parallel fan-out** — how LangGraph handles parallel branches that converge
- **Conditional edges** — `route_to_specialists()`, `route_after_reflection()`, `route_after_hitl()` — pure functions of state
- **`interrupt()` and `Command(resume=)`** — the suspension/resumption mechanism
- **`MemorySaver` vs `AsyncPostgresSaver`** — what gets persisted and why it matters for HITL
- **Pydantic `with_structured_output()`** — how LLMs are constrained to produce valid schemas
- **ReAct pattern** — Reason + Act loop, how `create_react_agent` implements it
- **asyncpg pool lifecycle** — `configure()` at startup, lazy `init_pool()` on first use, ContextVar injection
- **Qdrant vector search** — cosine similarity, 384-dim BAAI embeddings, collection/point/payload structure
- **DeepEval `@observe` decorator** — wraps LLM node calls, attaches metrics, reports to dashboard

### Data Models
- Every Pydantic model in `state.py` and what each field represents
- `IncidentRecord.embedding_text` construction (why query + causes + actions?)
- `CorrelationMatrix` — 6 pairs, what `linked: bool` means
- `ProposedAction.parameters` as a JSON string (not dict) — why?

---

## Section B: Concepts to Explain (Non-Technical Audience)

| Concept | Plain-English Explanation |
|---|---|
| **Agent** | A software "brain" that can ask questions, use tools, and decide what to do next — like an employee with a computer |
| **LangGraph** | A framework that lets you design the exact sequence of steps an AI takes, like drawing a flowchart it must follow |
| **Orchestrator** | The manager who reads your question, decides which team members to involve, and delegates specific tasks |
| **Specialist agents** | Four AI department heads (Sales, Inventory, Marketing, Support) — each only investigates their domain |
| **Aggregator** | The meeting room where all four specialists compare notes and agree on the root cause |
| **Reflection loop** | A quality check — if the AI isn't confident enough, it goes back and investigates more (max 2 retries) |
| **HITL (Human-in-the-Loop)** | The system asks a human for permission before touching anything. It can investigate freely but cannot act without approval |
| **MCP** | A universal plug socket that lets different AI tools (Claude, Copilot) connect to the same backend |
| **Vector memory (Qdrant)** | The AI's long-term memory — it stores every investigation so it can recall similar past incidents |
| **ReAct loop** | How a specialist thinks: "I'll check sales data... okay, now I'll check product breakdown... now I have enough to answer" |
| **Checkpoint** | A save-state for the AI. When it suspends for human approval, all progress is saved and resumes exactly where it left off |

---

## Section C: All Agentic AI & LangGraph Topics to Study

### LangGraph Core

| Topic | What to Know |
|---|---|
| `StateGraph` | Graph where state flows between nodes; vs `MessageGraph` (messages-only) |
| `TypedDict` state | Dict-like schema; every node returns a partial dict that is merged into state |
| `Annotated` + reducers | `Annotated[List[X], add_messages]` — custom merge logic instead of overwrite |
| `add_node()` | Registers a function as a graph node |
| `add_edge()` | Static directed edge between nodes |
| `add_conditional_edges()` | Edge whose target is decided by a function of state at runtime |
| `Send()` | Trigger a node with a copy of state; enables dynamic parallel fan-out |
| `START` / `END` | Sentinel entry/exit points |
| `compile()` / `CompiledStateGraph` | Compiles the builder into an executable graph |
| `graph.invoke()` | Synchronous single-shot invocation |
| `graph.ainvoke()` | Async single-shot invocation |
| `graph.astream()` | Async streaming — yields state snapshots or events as nodes execute |
| `graph.astream_events()` | Event-level streaming (used by Gradio UI for live updates) |
| `graph.get_state()` | Read the current checkpoint state for a thread |

### Checkpointing & Persistence

| Topic | What to Know |
|---|---|
| `MemorySaver` | In-process dict, dev only, lost on restart |
| `AsyncPostgresSaver` | Production-grade: full state saved to PostgreSQL after every node |
| `thread_id` in `configurable` | How LangGraph identifies sessions; maps to checkpoints |
| State snapshots | Immutable snapshots stored per step; enables time-travel and replay |

### Human-in-the-Loop (HITL)

| Topic | What to Know |
|---|---|
| `interrupt(value)` | Suspends the current node; serializes state; yields `value` to the caller |
| `Command(resume=value)` | Passes a value back into the suspended `interrupt()` call to resume |
| Graph suspension model | No thread blocking — state is persisted, graph is "done" until resumed |
| `graph.get_state()` + `.next` | How to detect if a graph is suspended (`.next` is non-empty) |
| Modification on resume | Human can pass back `modified_actions` — the graph accepts any JSON-serializable payload |

### Multi-Agent Patterns

| Topic | What to Know |
|---|---|
| Orchestrator-specialist pattern | Central router that delegates and collects results |
| Fan-out with `Send()` | Dynamic number of parallel branches from a list |
| ReAct pattern | `create_react_agent(llm, tools, prompt)` — Thought/Act/Observe loop |
| Subgraph vs flat node | This project uses flat nodes per specialist (not subgraphs); understand tradeoffs |
| State merging at convergence | How LangGraph waits for all Send() branches and merges results |

### LLM Integration (LangChain)

| Topic | What to Know |
|---|---|
| `AzureChatOpenAI` | Azure-hosted GPT; `azure_endpoint`, `azure_deployment`, `api_version` |
| `with_structured_output(PydanticModel)` | Forces LLM to return valid Pydantic object; uses tool-calling under the hood |
| `@tool` decorator | Turns an async Python function into a LangChain tool with schema |
| `create_react_agent` | Builds a ReAct loop agent from (llm, tools, prompt) — prebuilt |
| `SystemMessage` / `HumanMessage` | Role-tagged messages in the message list |
| Temperature=0 | Deterministic (reproducible) LLM outputs — critical for structured output |

### Memory & Retrieval

| Topic | What to Know |
|---|---|
| Short-term memory | LangGraph state — lives per session, clears after graph completes |
| Long-term memory | Qdrant — persists across sessions; retrieved by semantic similarity |
| Vector embeddings | Text → float vector (384-dim); semantically similar texts are close in vector space |
| Cosine similarity | Distance metric used by Qdrant for semantic search |
| `HuggingFaceEmbeddings` | Local CPU embedding (BAAI/bge-small-en-v1.5) — avoids API calls for embedding |
| `IncidentRecord` | Episodic memory unit; `embedding_text` = query + causes + actions |
| Qdrant upsert | Insert or update by vector ID |
| Qdrant scroll + filter | Filter by metadata field (e.g. intent type) |

### Observability & Evaluation

| Topic | What to Know |
|---|---|
| LangSmith tracing | Automatic trace of every LLM call, tool call, node execution |
| DeepEval `@observe` | Wraps a function, captures input/output, runs metrics, reports to DeepEval dashboard |
| `AnswerRelevancyMetric` | Is the output relevant to the input question? |
| `FaithfulnessMetric` | Is output grounded in retrieved context? Prevents hallucination |
| `TaskCompletionMetric` | Did the agent complete what it was asked to do? |
| `GEval` | Custom rubric-based evaluation using the LLM as a judge |
| `update_current_span(test_case=LLMTestCase(...))` | Registers evaluation data within the DeepEval trace span |
| Judge model | Same Azure GPT deployment used as the evaluator — evaluate the evaluator risk |

### MCP (Model Context Protocol)

| Topic | What to Know |
|---|---|
| MCP purpose | Standardized protocol for AI tools/agents to expose capabilities to LLM clients |
| `FastMCP` | Python library to build MCP servers quickly |
| Tool vs Prompt | Tool = callable function; Prompt = pre-built conversation starter |
| stdio transport | Default for local clients (Claude Code, Copilot); process-based communication |
| SSE transport | Server-Sent Events; for web-based MCP clients |
| `.mcp.json` | Config file that tells the MCP client how to start the server |
| Thin adapter principle | MCP tools contain no logic; just call `graph.ainvoke()` |

### Production Concerns

| Topic | What to Know |
|---|---|
| Async everywhere | Why asyncpg, `ainvoke`, `astream` — database I/O must not block the event loop |
| `ContextVar` | Thread/task-safe variable propagation without parameter threading |
| Connection pooling | `asyncpg.Pool` min/max size, `statement_cache_size=0` (prevents dirty state on cancellation) |
| Reflection loop safety | `max_reflection_retries` prevents infinite loops; always forces pass at limit |
| Checkpoint backend switch | `MemorySaver` → `AsyncPostgresSaver` for production durability |
| Pydantic `extra="forbid"` | Strict schema enforcement — rejects unexpected fields from LLM output |
| `model_validator(mode="after")` | Post-construction validation in Pydantic v2 (builds `database_url`) |

---

## Section D: Quick-Reference — "What does X do?"

| X | Answer |
|---|---|
| `interrupt()` | Suspends graph at current node, serializes state, returns control to caller |
| `Send()` | Dispatches a node with a copy of current state — enables parallel fan-out |
| `add_messages` | A reducer that appends new messages instead of replacing the messages list |
| `with_structured_output()` | Forces LLM output to conform to a Pydantic schema via tool-calling |
| `create_react_agent` | Builds a prebuilt ReAct (Thought-Act-Observe) loop agent |
| `MemorySaver` | In-memory checkpoint store (dev only) |
| `route_after_reflection()` | Conditional edge: loops back to orchestrator or advances to HITL |
| `route_after_hitl()` | Conditional edge: writes path (action_executor) or read-only path (output_formatter) |
| `IncidentRecord.embedding_text` | Concatenation of query + root_causes + actions — this is what gets vectorized |
| `@observe(metrics=[...])` | DeepEval decorator that captures LLM I/O and evaluates it against metrics |
| `configurable: {thread_id}` | Tells LangGraph which checkpoint to read/write — maps to a session |
| `ContextVar` | Async-safe way to pass session_id into tool functions without changing signatures |
