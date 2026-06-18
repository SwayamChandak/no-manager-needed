# Store Manager — E-Commerce Operations AI Agent

An AI-powered e-commerce operations management system that uses multi-agent LLM orchestration to diagnose business issues, execute corrective actions, and retrieve past incidents from memory. The system accepts natural language queries about sales, inventory, marketing, and customer support, routes them to specialized AI agents, correlates findings across domains, and proposes/executes actions with human approval (HITL).

---

## Features

- **Intent Classification** — Automatically routes queries to `diagnose`, `fix`, `recall`, or `summarize` workflows
- **Parallel Specialist Agents** — Independent ReAct agents for Sales, Inventory, Marketing, and Support domains
- **Cross-Domain Correlation** — Aggregator identifies root causes spanning multiple domains (e.g., low stock + high demand)
- **Human-in-the-Loop (HITL)** — Graph suspends before executing actions; operators approve, modify, or reject via UI
- **Semantic Memory** — Past incidents stored in Qdrant vector DB; recalled via semantic similarity search
- **Quality Reflection** — Reflection node validates coverage and retries with targeted sub-questions if gaps are found
- **Streaming Chat UI** — React frontend with real-time SSE streaming and an Approvals tab for HITL management
- **MCP Server** — Exposes agent tools over the Model Context Protocol for integration with Claude, Copilot, etc.

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

### Key Modules

| Module | Role |
|--------|------|
| `agent/` | LangGraph state machine, orchestrator, specialists, aggregator, reflection, HITL, action executor |
| `tools/` | Domain tools for inventory, sales, marketing, support, CRM, analytics, and actions |
| `memory/` | Long-term (Qdrant vector store) and short-term (in-session) memory |
| `mcp_server/` | FastMCP SSE server exposing agent tools via Model Context Protocol |
| `api/` | FastAPI app server with HITL endpoints and React UI proxy |
| `db/` | PostgreSQL migrations, seed data, and async connection helpers |
| `eval/` | DeepEval metrics for routing correctness, relevancy, faithfulness |
| `ui-react/` | React + Tailwind chat interface with streaming and approval management |

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
- React 19, Tailwind CSS, Zustand, Radix UI
- Server-Sent Events for streaming responses

**Infrastructure**
- Docker & Docker Compose
- Nginx (React SPA proxy)

---

## Services

| Service | Port | Purpose |
|---------|------|---------|
| `postgres` | 5433 | PostgreSQL 16 database |
| `qdrant` | 6334 | Vector store for incident memory |
| `db-init` | — | One-shot: migrations + seed (exits after completion) |
| `mcp-server` | 8000 | LangGraph MCP server (SSE) |
| `app-server` | 8002 | FastAPI app + HITL endpoints + React proxy |
| `ui-react` | 3000 | React chat UI (Nginx) |

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
# Azure OpenAI
AZURE_OPENAI_API_KEY=<your-key>
AZURE_OPENAI_ENDPOINT=https://<region>.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=gpt-4o
AZURE_OPENAI_API_VERSION=2024-02-01

# PostgreSQL (defaults work with Docker Compose)
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_USER=ops_user
POSTGRES_PASSWORD=ops_password
POSTGRES_DB=ops_agent

# Qdrant (defaults work with Docker Compose)
QDRANT_URL=http://qdrant:6333

# Optional: LangSmith tracing
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=store-manager
```

### 2. Start All Services

```bash
docker compose up --build
```

### 3. Access the Application

| Interface | URL |
|-----------|-----|
| Chat UI | http://localhost:3000 |
| App Server API | http://localhost:8002 |
| MCP Server (SSE) | http://localhost:8000/sse |
| PostgreSQL | `postgresql://ops_user:ops_password@localhost:5433/ops_agent` |
| Qdrant Dashboard | http://localhost:6333/dashboard |

---

## Local Development (without Docker)

```bash
# Install Python dependencies
pip install -r requirements.txt

# Run database migrations and seed
python -m db.migrate
python -m db.seed

# Terminal 1 — MCP Server
python -m mcp_server

# Terminal 2 — App Server
python -m api

# Terminal 3 — React UI (dev server)
cd ui-react
npm install
npm start     # Proxies /api to localhost:8002, runs on port 3000
```

---

## API Reference

### Chat (App Server)

```
POST /chat/stream
Content-Type: application/json

{
  "message": "Why are sales down this week?",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "intent": "auto"   // "auto" | "diagnose" | "fix" | "recall" | "summarize"
}

→ Server-Sent Events stream
```

### HITL Endpoints

```
GET  /hitl/status/{session_id}
     → { "status": "pending", "proposed_actions": [...] }

POST /hitl/{session_id}/approve
     { "modified_actions": [...], "comment": "Looks good" }
     → { "status": "approved" }

POST /hitl/{session_id}/reject
     { "reason": "Insufficient data" }
     → { "status": "rejected" }
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
│   ├── orchestrator.py     # Intent classifier & specialist fan-out
│   ├── aggregator.py       # Cross-domain analysis & action proposals
│   ├── reflection.py       # Quality validation node
│   ├── hitl.py             # Human-in-the-loop interrupt node
│   ├── action_executor.py  # Tool execution for approved actions
│   ├── output_formatter.py # Final response structuring
│   ├── state.py            # LangGraph TypedDict state definition
│   └── specialists/        # Domain ReAct agents (sales, inventory, marketing, support)
├── tools/                  # All agent tools
│   ├── registry.py         # @safe_tool decorator & authorization
│   ├── inventory.py        # Stock, stockouts, restock
│   ├── sales.py            # Revenue, orders, anomalies
│   ├── marketing.py        # Campaigns, channel metrics
│   ├── support.py          # Complaints, sentiment, tickets
│   ├── crm.py              # Customer data, churn risk
│   ├── analytics.py        # Aggregated metrics & forecasting
│   └── actions.py          # Executable corrective actions
├── memory/                 # Short-term and long-term memory
├── mcp_server/             # FastMCP SSE server
├── api/                    # FastAPI app server & HITL endpoints
├── db/                     # Migrations, seed data, connection helpers
├── eval/                   # DeepEval metrics & test runner
├── ui-react/               # React + Tailwind frontend
├── config.py               # Centralized configuration
├── docker-compose.yml
└── requirements.txt
```
