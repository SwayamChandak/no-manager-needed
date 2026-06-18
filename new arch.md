```mermaid
graph TB
    subgraph P2["Process 2 — App Server (python -m api) :8002"]
        UI["Gradio UI\n/ui"]
        CHAT["POST /chat\n(MCP proxy)"]
        HITL_API["HITL API\n/hitl/approve\n/hitl/reject\n/hitl/pending"]
        HTTPX["httpx client"]

        UI -->|user message| CHAT
        UI -->|approve/reject| HITL_API
        CHAT --> HTTPX
    end

    subgraph P1["Process 1 — MCP Server (python -m mcp_server) :8000"]

        subgraph MCPTOOLS["mcp_server/mcp_tools.py — MCP Tools"]
            T_DIAG["diagnose(question, session_id)\ngraph.ainvoke intent=diagnose"]
            T_FIX["fix(query, session_id, resume, approved)\ngraph.ainvoke intent=fix\nhandles interrupt + Command resume"]
            T_SUM["summarize(date_range, focus_areas)\ngraph.ainvoke intent=summarize"]
            T_REC["recall(scenario_description, top_k)\nqdrant search_similar ONLY\n(no graph invocation)"]
        end

        subgraph GRAPH["LangGraph StateGraph"]
            ORC["orchestrator_node\n(LLM — intent + routing)"]

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

    HTTPX -->|MCP SSE protocol| MCPTOOLS
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

**Key points the diagram shows:**

- **Two separate OS processes** — the App Server never touches graph code directly except for HITL resume, which works because both processes share `AsyncPostgresSaver` on PostgreSQL.
- **MCP tools** — `diagnose`, `fix`, and `summarize` invoke the LangGraph graph. `recall` bypasses the graph entirely and queries Qdrant directly, returning raw results.
- **recall_node** — when the orchestrator classifies intent as `recall` (triggered via `diagnose`/`summarize` MCP tools), the graph short-circuits: no specialists, no aggregator, no reflection, no HITL. Goes straight to `output_formatter_node` with `retrieved_memories` populated.
- **Tool registry** — all 4 specialists and the action executor call `get_tools_for_agent()` at runtime; no hardcoded imports.
- **Reflection loop** — feeds back to the orchestrator on failure, advances to HITL on pass.
- **HITL cross-process** — the App Server's HITL API calls `graph.ainvoke(Command(resume=...))` directly, bypassing the MCP Server, because the checkpoint lives in PostgreSQL.
- **memory_writer_node** — only on the `action_executor → memory_writer → output_formatter` path; never triggered for read-only intents.

---

## Architecture Review Q&A

### Is the architecture correct?

Yes, the overall structure is sound. The two-process split (MCP Server + App Server), shared PostgreSQL checkpoint for cross-process HITL resume, Qdrant for vector memory, and the LangGraph StateGraph topology are all coherent and follow established patterns for production agentic systems.

One gap worth noting: the `recall` MCP tool queries Qdrant directly (bypassing the graph), but the `recall_node` inside the graph is only reachable via `diagnose` or `summarize`. These are two separate recall paths — make sure this is intentional and that both paths use the same `search_similar` logic, otherwise they can diverge.

---

### Who decides the queries for each specialist agent?

**The orchestrator decides everything above the specialist level.** There are two distinct layers:

1. **Orchestrator LLM** (`orchestrator.py`) — on every invocation it:
   - Classifies `intent` (`diagnose`, `fix`, `recall`, `summarize`)
   - Selects which subset of the 4 specialists are relevant
   - **Generates a specific, tailored sub-question for each selected specialist** (e.g. `[SALES_SUBQUESTION] Did revenue drop on 2026-06-12 and in which product categories?`)
   - Injects those tagged `HumanMessage` objects into `state["messages"]`

2. **Specialist ReAct loops** (`specialists/*.py`) — each specialist only decides **which tools to call** (and with what parameters) to answer the sub-question the orchestrator already wrote for it. The sub-question itself is not composed by the specialist.

   Each specialist scans `state["messages"]` for its own tag (e.g. `[SALES_SUBQUESTION]`) to extract its assigned question. If no tag is found it falls back to the raw `user_query` — which is a fallback, not the intended path.

**On reflection re-entry**, the orchestrator generates *refined* follow-up sub-questions only for the specialists that had gaps, so the loop is also orchestrator-driven.

**Implication:** if the user asks a pure inventory question the orchestrator will set `active_specialists = ["inventory"]` and only that specialist runs — not all 4. The fan-out is selective, not always-4.

---

**Bug found in code (not in diagram):** `orchestrator.py` does not write `decision.intent` back to state. It returns `active_specialists`, `messages`, and `tool_call_log`, but omits `"intent": decision.intent`. The `intent` field is only set by `_build_initial_state` in the MCP tool (as `intent_hint`). This means if the orchestrator LLM reclassifies the intent differently from the MCP tool's hint, the routing logic (`route_after_hitl`, `route_to_specialists`) will use the stale initial value. Fix: add `"intent": decision.intent` to the `return` dict in `_run_orchestrator_impl`.

---

### Are only 4 tools exposed to the MCP client, and is this format correct?

Yes — exactly 4 tools are exposed: `diagnose`, `fix`, `summarize`, `recall`. This is the correct design pattern.

**Why this is right:**
- The MCP client (the App Server / Gradio UI) expresses **intent**, not implementation. It doesn't need to know about `analytics.py`, `crm.py`, etc. Those are internal to the graph.
- Exposing individual low-level tools (inventory lookup, campaign fetch, etc.) to the MCP client would make the client responsible for orchestration — defeating the purpose of the agentic system.
- The 4 tools map cleanly to the 4 user-facing intents. The graph handles all routing, specialist selection, reflection, and HITL internally.

**The only exception** is `recall`, which bypasses the graph entirely — this is a deliberate optimization (pure retrieval, no reasoning needed). That is a valid and common pattern.