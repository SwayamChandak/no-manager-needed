# Store Manager — E-Commerce Operations AI Agent

An AI-powered e-commerce operations management system that uses multi-agent LLM orchestration to diagnose business issues, execute corrective actions, and retrieve past incidents from memory. The system accepts natural language queries about sales, inventory, marketing, and customer support, routes them to specialized AI agents, correlates findings across domains, and proposes/executes actions with human approval (HITL).

---

## Features

- **Intent Classification + Guardrails** — Automatically routes queries to `diagnose`, `fix`, `recall`, or `summarize`; rejects out-of-scope questions with a user-facing explanation
- **Parallel Specialist Agents** — Independent ReAct agents for Sales, Inventory, Marketing, and Support domains, each with scoped tool access via `@safe_tool` decorator
- **Cross-Domain Correlation** — Aggregator identifies root causes spanning multiple domains (e.g., low stock + high demand)
- **Human-in-the-Loop (HITL)** — Graph suspends before executing actions; operators approve, modify, or reject via the Approvals tab
- **Semantic Memory** — Past incidents stored in Qdrant vector DB; recalled via semantic similarity search
- **Quality Reflection** — Reflection node validates coverage and retries with targeted sub-questions if gaps are found
- **Streaming Chat UI** — React 19 + Tailwind + Radix UI + Zustand frontend with real-time SSE streaming, Markdown rendering (react-markdown + remark-gfm), rich artifact cards (root causes with confidence bars, recommended actions with type-coloured borders), agent trace badges, starter suggestion chips, live activity log, and a dedicated Approvals tab for HITL action management (selective checkbox approval with rejection reason)
- **MCP Server** — FastMCP SSE server exposing agent tools (`diagnose`, `fix`, `recall`, `summarize`) over the Model Context Protocol for integration with Claude, Copilot, etc.

---

## Architecture

```
User Query
    ↓
[Orchestrator] — Intent classification & specialist fan-out
    ↓
[Parallel Specialists] — Sales | Inventory | Marketing | Support
    ↓
[Aggregator] — Cross-domain root cause analysis & action proposals
    ↓
[Reflection] — Quality validation; retry if gaps detected
    ↓
[HITL Node] — Human approval via Approvals UI
    ↓
[Action Executor] — Execute approved actions (restock, discounts, tickets, …)
    ↓
[Memory Writer] — Persist incident to Qdrant for future recall
    ↓
[Output Formatter] — Stream structured response to user
```

### Detailed Architecture

```mermaid
graph TB
    subgraph P3["Process 3 — React UI (npm start) :3000 / Nginx :80"]
        UI["React 19 SPA\nRadix UI Tabs + Zustand store"]
        UI_CHAT["Chat Tab\nChatHistory + MessageInput\nStarterPrompts + ActivityLog"]
        UI_APPR["Approvals Tab\nActionCheckboxGroup\nApprovalButtons\nRejectionReasonInput"]

        UI --> UI_CHAT
        UI --> UI_APPR
    end

    subgraph P2["Process 2 — App Server (python -m api) :8002"]
        API["FastAPI app"]
        STATIC["/ui\nReact build (StaticFiles)"]
        CHAT["POST /chat/stream\n(SSE — calls mcp_tools directly)"]
        HITL_API["/hitl/pending\n/hitl/approve/{id}\n/hitl/reject/{id}\n/hitl/modify/{id}"]
        MCP_PROXY_IMPORT["mcp_server.mcp_tools\n(direct import)"]

        API --> STATIC
        API --> CHAT
        API --> HITL_API
        CHAT --> MCP_PROXY_IMPORT
    end

    subgraph P1["Process 1 — MCP Server (python -m mcp_server) :8000"]

        subgraph MCPTOOLS["mcp_server/mcp_tools.py — MCP Tools"]
            T_DIAG["diagnose(question, session_id)\ngraph.ainvoke intent=diagnose"]
            T_FIX["fix(query, session_id, resume, approved)\ngraph.ainvoke intent=fix\nhandles interrupt + Command resume"]
            T_SUM["summarize(date_range, focus_areas)\ngraph.ainvoke intent=summarize"]
            T_REC["recall(scenario_description, top_k)\nqdrant search_similar ONLY\n(no graph invocation)"]
        end

        subgraph GRAPH["LangGraph StateGraph"]
            ORC["orchestrator_node\n(LLM — intent + routing + guardrails)"]

            subgraph FAN["Parallel fan-out via Send() — intent ≠ recall"]
                S["sales_node\nReAct"]
                I["inventory_node\nReAct"]
                M["marketing_node\nReAct"]
                SP["support_node\nReAct"]
            end

            RCN["recall_node\n(Qdrant search_similar)\nintent = recall only"]

            AGG["aggregator_node\n(LLM — correlation)"]
            REF["reflection_node\n(deterministic QA)"]
            HITL_N["hitl_node\ninterrupt()"]
            AE["action_executor_node"]
            MW["memory_writer_node\n(write_incident → Qdrant)"]
            OF["output_formatter_node\n(LLM — Markdown report)"]
        end

        REG["tools/registry.py\n_REGISTRY per agent"]

        T_DIAG & T_FIX & T_SUM -->|graph.ainvoke| GRAPH
        ORC -->|intent=recall| RCN
        ORC -->|intent≠recall\nroute_to_specialists| FAN
        RCN --> OF
        S & I & M & SP --> AGG
        AGG --> REF
        REF -->|passed| HITL_N
        REF -->|failed + retries left| ORC
        HITL_N -->|intent=fix| AE
        HITL_N -->|intent≠fix| OF
        AE --> MW
        MW --> OF

        S & I & M & SP -.->|get_tools_for_agent| REG
        AE -.->|get_tools_for_agent| REG
    end

    subgraph TOOLS["tools/"]
        ANAL["analytics.py\n@safe_tool(agents=['sales'])"]
        INV["inventory.py\n@safe_tool(agents=['inventory'])"]
        CAMP["campaigns.py\n@safe_tool(agents=['marketing'])"]
        CRM["crm.py\n@safe_tool(agents=['support'])"]
        ACT["actions.py\n@safe_tool(agents=['action_executor'])"]
    end

    subgraph INFRA["Shared Infrastructure"]
        PG[("PostgreSQL\nstore schema\nLangGraph checkpoints")]
        QD[("Qdrant\nincident_memory")]
    end

    UI_CHAT -->|SSE fetch| CHAT
    UI_APPR -->|approve/reject| HITL_API
    HITL_API -->|graph.ainvoke Command resume| GRAPH

    S --> ANAL
    I --> INV
    M --> CAMP
    SP --> CRM
    AE --> ACT

    TOOLS -->|asyncpg pool| PG
    HITL_N -->|AsyncPostgresSaver| PG
    HITL_API -->|AsyncPostgresSaver| PG
    MW -->|write_incident| QD
    RCN -->|search_similar| QD
    T_REC -->|search_similar direct| QD
```

**Key points:**
- **Three separate OS processes** — React UI (Nginx/dev), App Server (FastAPI), and MCP Server (LangGraph). MCP only runs via Docker or as a standalone process for external MCP clients; the App Server imports `mcp_tools` directly.
- **App Server calls MCP tools directly** — `api/app.py` imports `mcp_server.mcp_tools` and routes all four intents through their corresponding tool functions (no HTTP proxy between App Server and MCP).
- **MCP tools** — exposed via FastMCP SSE so Claude, Copilot, or any MCP client can invoke them. `diagnose`, `fix`, and `summarize` invoke the LangGraph graph. `recall` bypasses the graph entirely and queries Qdrant directly.
- **Intent guardrails** — the App Server runs an LLM-based classifier *before* invoking the graph; out-of-scope queries (general knowledge, personal advice, etc.) are rejected with a user-facing message and never reach the graph.
- **recall_node** — when intent is `recall`, the graph short-circuits: no specialists, no aggregator, no reflection, no HITL. Goes straight to `output_formatter_node`.
- **Tool registry** — all 4 specialists and the action executor call `get_tools_for_agent()` at runtime via `@safe_tool(agents=[...])` decorator; no hardcoded imports.
- **Reflection loop** — feeds back to the orchestrator on failure, advances to HITL on pass.
- **HITL cross-process** — the App Server's HITL API calls `graph.ainvoke(Command(resume=...))` directly (same process), because the checkpoint lives in PostgreSQL. The MCP Server is *not* involved in HITL resume.
- **memory_writer_node** — only triggered on the `action_executor → memory_writer → output_formatter` path; never for read-only intents.

### Key Modules

| Module | Role |
|--------|------|
| `agent/` | LangGraph state machine, orchestrator (incl. intent guardrails), specialists (Sales, Inventory, Marketing, Support), aggregator, reflection, HITL, action executor |
| `tools/` | Domain tools (`@safe_tool` decorator): inventory, sales, marketing, support, CRM, analytics, and actions |
| `memory/` | Long-term (Qdrant vector store — incident memory) and short-term (in-session) memory |
| `mcp_server/` | FastMCP SSE server exposing `diagnose`, `fix`, `recall`, `summarize` via MCP protocol |
| `api/` | FastAPI app server: `/chat/stream` SSE endpoint, HITL API (`/hitl/approve`, `/hitl/reject`, `/hitl/pending`), React SPA static mount |
| `db/` | PostgreSQL migrations (`db.migrate`), seed data (`db.seed`, `db.seed_extra`), `AsyncConnectionPool` helper |
| `eval/` | DeepEval metrics for routing correctness, relevancy, faithfulness |
| `ui-react/` | React 19 + Tailwind + Radix UI + Zustand chat interface with SSE streaming, Markdown rendering, artifact cards, activity log, and approval management |

---

## Tech Stack

**Backend**
- Python 3.11
- [LangGraph](https://github.com/langchain-ai/langgraph) — stateful multi-agent orchestration
- [LangChain](https://github.com/langchain-ai/langchain) — LLM integrations & tool management
- [FastAPI](https://fastapi.tiangolo.com/) / Uvicorn — REST & SSE API server
- [FastMCP](https://github.com/jlowin/fastmcp) — Model Context Protocol server
- Azure OpenAI — LLM (GPT-4o)
- [Qdrant](https://qdrant.tech/) — vector database for incident memory
- PostgreSQL 16 — relational store for business & ops state
- [DeepEval](https://github.com/confident-ai/deepeval) — LLM quality evaluation

**Frontend**
- React 19, Tailwind CSS, Zustand (state management), Radix UI (primitives)
- react-markdown + remark-gfm for rich Markdown rendering
- Server-Sent Events (SSE) for streaming responses

**Infrastructure**
- Docker & Docker Compose
- Nginx (serves React SPA in production)

---

## Services

| Service | Port | Purpose |
|---------|------|---------|
| `postgres` | 5433 (host) / 5432 (container) | PostgreSQL 16 database (store schema + LangGraph checkpoints) |
| `qdrant` | 6334 (host) / 6333 (container) | Vector store for incident memory |
| `db-init` | — | One-shot: runs `db.migrate` + `db.seed` (exits after completion) |
| `mcp-server` | 8000 | FastMCP SSE server — exposes `diagnose`/`fix`/`recall`/`summarize` tools |
| `app-server` | 8002 | FastAPI app — `/chat/stream` SSE, HITL API endpoints, React SPA mount at `/ui` |
| `ui-react` | 3000 (host) / 80 (container) | React 19 chat UI (served by Nginx in Docker; `npm start` in dev) |

---

## Getting Started

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- Azure OpenAI resource with a GPT-4o deployment

### 1. Configure Environment

Copy the example environment file and fill in your credentials:

```bash
cp .env.example .env
```

```env
# ── Azure OpenAI (required) ───────────────────────────────────────────────────
AZURE_OPENAI_API_KEY=your-azure-openai-api-key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com
AZURE_OPENAI_DEPLOYMENT=gpt-4o
AZURE_OPENAI_API_VERSION=2024-02-01

# Azure OpenAI — Embeddings
AZURE_EMBEDDING_DEPLOYMENT=text-embedding-3-small

# ── LangSmith observability (optional) ───────────────────────────────────────
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=ecommerce-ops-agent

# ── PostgreSQL credentials ────────────────────────────────────────────────────
POSTGRES_DB=ops_agent
POSTGRES_USER=ops_user
POSTGRES_PASSWORD=ops_password

# ── LangGraph checkpoint backend ─────────────────────────────────────────────
CHECKPOINT_BACKEND=postgres
```

### 2. Start All Services

```bash
docker compose up --build
```

---

## Local Development (without Docker)

### Prerequisites

- Python 3.11+
- Node.js 18+
- PostgreSQL 16 running on `localhost:5432`
- Qdrant running on `http://localhost:6333` (or update `.env`)
- Azure OpenAI resource with GPT-4o and text-embedding-3-small deployments

### 1. Configure Environment

```bash
cp .env.example .env
# Edit .env with your Azure OpenAI credentials and local DB/Qdrant settings
```

### 2. Install Dependencies

```bash
# Python
pip install -r requirements.txt

# React UI
cd ui-react
npm install
cd ..
```

### 3. Start the Servers

The project runs as **three separate processes**. Start them in separate terminals:

#### Terminal 1 — Database Init (one-time)

```bash
python -m db.migrate
python -m db.seed
```

Runs PostgreSQL migrations and seeds the database with sample data (products, orders, customers, campaigns, support tickets).

#### Terminal 2 — MCP Server (Process 1, port 8000)

```bash
python -m mcp_server
```

Starts the FastMCP SSE server that hosts the LangGraph state machine. Required before the App Server starts. Also seeds Qdrant with synthetic incidents on first run.

#### Terminal 3 — App Server (Process 2, port 8002)

```bash
python -m api
```

Starts the FastAPI app server with:
- `POST /chat/stream` — SSE streaming endpoint (calls `mcp_tools` directly)
- `/hitl/approve`, `/hitl/reject`, `/hitl/pending` — HITL management API
- `/ui` — serves the React SPA build (if `ui-react/build/` exists)

#### Terminal 4 — React UI Dev Server (Process 3, port 3000)

```bash
cd ui-react
npm start
```

Runs the React 19 dev server with hot reload. The SPA fetches directly from the App Server at `http://localhost:8002`.

### Quick Start (all in one terminal using background processes — Windows)

```powershell
# Terminal 1: DB init
python -m db.migrate; if ($?) { python -m db.seed }

# Then start all servers:
Start-Process powershell -ArgumentList "python -m mcp_server"
Start-Process powershell -ArgumentList "python -m api"
Start-Process "npm" -ArgumentList "run start" -WorkingDirectory ui-react
```

### 4. Access the Application

| Interface | URL |
|-----------|-----|
| Chat UI (dev) | http://localhost:3000 |
| Chat UI (Docker) | http://localhost:3000 |
| App Server API | http://localhost:8002 |
| MCP Server (SSE) | http://localhost:8000/sse |
| PostgreSQL | `postgresql://ops_user:ops_password@localhost:5433/ops_agent` |
| Qdrant Dashboard | http://localhost:6333/dashboard |

---

## API Reference

### Chat (App Server)

```
POST /chat/stream
Content-Type: application/json

{
  "message": "Why are sales down this week?",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "intent": "auto"
}

→ Server-Sent Events stream

Event types (JSON per `data:` line):
  intent_classified — { type, intent } | off_topic — { type, message } (rejected)
  node_start        — { type, node }
  node_end          — { type, node }
  token             — { type, node, content }  ← live LLM token (Stream tab)
  tool_start        — { type, node, tool, input_preview }
  tool_end          — { type, node, tool }
  interrupt         — { type, proposed_actions, status, session_id }
  result            — { type, session_id, finding, root_causes, confidence,
                        supporting_data, recommended_actions, actions_taken, ... }
  error             — { type, message, detail }
```

### HITL Endpoints

```
GET  /hitl/pending
     → [ "session_id_1", "session_id_2", ... ]

GET  /hitl/pending/{session_id}
     → { "session_id": "...", "status": "awaiting_approval", "proposed_actions": [...] }

POST /hitl/approve/{session_id}
     { "modified_actions": [...], "comment": "Looks good" }
     → { "session_id": "...", "status": "executed", "message": "..." }

POST /hitl/reject/{session_id}
     { "reason": "Insufficient data" }
     → { "session_id": "...", "status": "rejected", "message": "..." }

POST /hitl/modify/{session_id}
     { "modified_actions": [...], "comment": "..." }
     → { "session_id": "...", "status": "executed", "message": "..." }

GET  /hitl/health
     → { "status": "ok", "timestamp": "..." }
```

### MCP Tools (exposed to Claude, Copilot, etc.)

| Tool | Description |
|------|-------------|
| `diagnose` | Analyze issues across sales, inventory, marketing, support |
| `fix` | Diagnose and propose corrective actions (requires HITL approval) |
| `recall` | Retrieve similar past incidents from long-term memory |
| `summarize` | Executive health overview across all domains |

---

## Evaluation

Quality metrics are implemented with [DeepEval](https://github.com/confident-ai/deepeval):

```bash
python -m eval.run_evals
```

Metrics include routing correctness, answer relevancy, root cause quality, and faithfulness — one set per major graph node.

---

## Project Structure

```
store manager/
├── agent/                  # LangGraph graph & agent nodes
│   ├── graph.py            # StateGraph definition & routing logic
│   ├── orchestrator.py     # Intent classifier & specialist fan-out (with guardrails)
│   ├── aggregator.py       # Cross-domain analysis & action proposals
│   ├── reflection.py       # Quality validation node (deterministic QA)
│   ├── hitl.py             # Human-in-the-loop interrupt node
│   ├── action_executor.py  # Tool execution for approved actions
│   ├── output_formatter.py # Final response structuring (Markdown)
│   ├── state.py            # LangGraph TypedDict state definition
│   └── specialists/        # Domain ReAct agents (sales, inventory, marketing, support)
├── tools/                  # All agent tools with @safe_tool decorator
│   ├── registry.py         # @safe_tool decorator & runtime tool authorization
│   ├── inventory.py        # Stock levels, stockouts, restock orders
│   ├── sales.py            # Revenue, orders, anomalies, product trends
│   ├── marketing.py        # Campaigns, promotions, channel metrics
│   ├── support.py          # Complaints, sentiment, support tickets
│   ├── crm.py              # Customer data, churn risk, segments
│   ├── analytics.py        # Aggregated metrics & forecasting
│   └── actions.py          # Executable corrective actions (restock, discount, ticket, campaign)
├── memory/                 # Short-term (in-session) and long-term (Qdrant) memory
│   └── long_term.py        # Qdrant vector store — seed_memory(), write_incident(), search_similar()
├── mcp_server/             # FastMCP SSE server (Process 1)
│   ├── server.py           # FastMCP app with 4 tools + 6 prompts
│   ├── mcp_tools.py        # Graph invocation wrappers (diagnose, fix, recall, summarize)
│   └── schemas.py          # Pydantic models for tool I/O
├── api/                    # FastAPI app server (Process 2)
│   ├── app.py              # FastAPI app — /chat/stream SSE + /ui static mount
│   ├── hitl_api.py         # HITL sub-app — approve/reject/modify/pending endpoints
│   └── hitl_store.py       # In-memory registry of pending HITL session IDs
├── db/                     # PostgreSQL — migrations, seeds, connection pool
│   ├── connection.py       # AsyncConnectionPool helper
│   ├── migrate.py          # Run pending migrations
│   ├── seed.py             # Seed sample data (products, orders, customers, etc.)
│   └── migrations/         # SQL migration files
├── eval/                   # DeepEval quality metrics & test runner
│   └── run_evals.py        # Routing correctness, relevancy, faithfulness metrics
├── ui-react/               # React 19 + Tailwind + Radix UI frontend (Process 3)
│   └── src/
│       ├── App.js          # Root — Tabs (Chat | Approvals)
│       ├── components/
│       │   ├── ChatTab.jsx, ChatHistory.jsx, ChatMessage.jsx
│       │   ├── MessageInput.jsx, StarterPrompts.jsx, ActivityLog.jsx
│       │   ├── ApprovalsTab.jsx, ActionCheckboxGroup.jsx
│       │   ├── ApprovalButtons.jsx, RejectionReasonInput.jsx
│       │   └── ui/         # Radix UI primitives (button, checkbox, tabs, scroll-area, badge, textarea)
│       ├── hooks/
│       │   ├── useChatStream.js  # SSE streaming hook
│       │   └── useHitl.js        # HITL approve/reject hook
│       ├── store/
│       │   └── useChatStore.js   # Zustand store
│       └── lib/
│           ├── api.js            # fetch helpers for /chat/stream and /hitl endpoints
│           ├── constants.js      # Specialist colours, starter prompts, node labels
│           ├── sseStream.js      # SSE parser utility
│           └── utils.js          # cn() classname utility
├── config.py               # Centralized Pydantic Settings
├── docker-compose.yml      # 6 services: postgres, qdrant, db-init, mcp-server, app-server, ui-react
├── Dockerfile              # PostgreSQL 16 image with baked POSTGRES_DB=ops_agent
├── Dockerfile.app          # Python 3.11 app image
└── requirements.txt
```
