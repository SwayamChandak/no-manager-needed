# Error Log — Store Manager Agent

All errors encountered during development of this session and how each was resolved.

---

## 1. Campaign launch approved but not saved to the database

**Symptom:**  
User approved a "launch campaign" HITL action for `laptop_new` with a 15% discount. The assistant narrated success, but no row appeared in `store.campaigns`.

**Root cause:**  
The `ACTION_TOOL_MAP` in `agent/action_executor.py` had no entry for creating a new campaign. The aggregator LLM proposed an action type the executor didn't recognise, which silently hit the `"No tool registered"` branch and recorded `status="failed"`. The output formatter's LLM still narrated success because it was reading the proposed action, not the executed result.

**Fix:**  
- Added `launch_campaign` tool to `tools/actions.py` — inserts a row into `store.campaigns` and optionally into `store.promotions`.  
- Registered `"launch_campaign": launch_campaign` in `ACTION_TOOL_MAP`.  
- Added `launch_campaign` to the action type reference in the aggregator prompt so the LLM knows to use it.

---

## 2. `deepeval inspect` — no test_run_*.json file found

**Symptom:**  
```
Error: Invalid value: No test_run_*.json file found.
```
Ran the chatbot with a prompt, then ran `deepeval inspect` — it errored immediately.

**Root cause:**  
`@observe` decorators alone (used on the nodes) do not write a local snapshot file. The `test_run_*.json` file is only created when DeepEval's evaluation loop owns the run via `evals_iterator()`. Running the chatbot normally does not trigger that loop.

**Fix:**  
Created `eval/run_evals.py` — a standalone batch evaluation script that uses `evals_iterator()` to wrap each graph invocation. Running `python eval/run_evals.py` creates the snapshot; `deepeval inspect` can then read it.

---

## 3. `ModuleNotFoundError: No module named 'textual'`

**Symptom:**  
```
ModuleNotFoundError: No module named 'textual'
```
Raised when running `deepeval inspect` after `run_evals.py` completed successfully.

**Root cause:**  
DeepEval 4.0's inspect TUI depends on `textual` for its terminal UI, but `textual` is not bundled with `deepeval` and was not installed in the project's virtual environment.

**Fix:**  
```bash
uv add textual
```

---

## 4. Shared metric instances across concurrent specialist nodes

**Symptom:**  
All four specialist nodes (sales, inventory, marketing, support) were decorated with `@observe(metrics=specialist_metrics())`. Since metrics store mutable state (`.score`, `.reason`), concurrent specialist runs shared the same instances — later runs could overwrite scores from earlier ones.

**Root cause:**  
A single `specialist_metrics()` factory was shared, producing one set of instances evaluated at decoration time, reused across all parallel nodes.

**Fix:**  
Replaced the single `specialist_metrics()` factory with four domain-specific factories: `sales_metrics()`, `inventory_metrics()`, `marketing_metrics()`, `support_metrics()`. Each specialist module imports its own factory, producing isolated metric instances per node.

---

## 5. `FaithfulnessMetric` had no retrieval context

**Symptom:**  
`FaithfulnessMetric` was added to specialist nodes but would always score against an empty context, making it meaningless — it cannot check groundedness without knowing what the tools actually returned.

**Root cause:**  
The `LLMTestCase` in each specialist's `update_current_span(...)` only set `input` and `actual_output`. The `retrieval_context` field, which `FaithfulnessMetric` uses to verify the response is grounded in retrieved data, was not populated.

**Fix:**  
Each specialist node now passes tool outputs into the test case:
```python
update_current_span(
    test_case=LLMTestCase(
        input=sub_question,
        actual_output=final_message,
        retrieval_context=[json.dumps(o, default=str) for o in tool_outputs[:6]],
    )
)
```

---

## 6. Aggregator `Root Cause Quality` metric scoring low / failing

**Symptom:**  
```
The Actual Output provides a specific date and mentions no complaints, which aligns
partially with the Input's query. However, it fails to address cross-domain connections
or provide meaningful analysis beyond the absence of complaints.
```
The aggregator node was scoring very low on its `Root Cause Quality` GEval metric despite the aggregator producing correct structured output.

**Root cause:**  
`update_current_span(actual_output=output.summary)` only passed the one-sentence summary paragraph to the judge. The `Root Cause Quality` rubric checks for:
- Ranked root causes with confidence scores → in `output.root_causes`
- Cross-domain correlations → in `output.correlation_matrix`
- Proposed actions with justifications → in `output.proposed_actions`

The judge never saw any of those fields and correctly scored the output as incomplete.

**Fix:**  
Added `_build_aggregator_output_text(output)` helper in `agent/aggregator.py` that flattens all output fields into a single structured text block (summary + root causes + proposed actions + cross-domain links). This is now passed as `actual_output` so the judge evaluates the full analysis.

---

## 7. `IndentationError` in `eval/deepeval_setup.py`

**Symptom:**  
```
IndentationError: unexpected indent
  File "eval/deepeval_setup.py", line 263
```

**Root cause:**  
A partial string replacement left a duplicate closing `),\n    ]` from the old `output_formatter_metrics()` function body still present after the new function body was written.

**Fix:**  
Removed the orphaned `),\n    ]` lines.

---

## 8. `LengthFinishReasonError` — judge hitting token output limit

**Symptom:**  
```
openai.LengthFinishReasonError: Could not parse response content as the length
limit was reached — completion_tokens=8000
```
DeepEval's metric judge exhausted its output token budget mid-JSON, causing the structured output parser to fail on a truncated response.

**Root cause:**  
No `max_tokens` limit was set on the `AzureOpenAIModel` judge instance. The model defaulted to its maximum output window (8,192 tokens) and generated verbose reasoning until it hit the ceiling, leaving the JSON incomplete.

**Fix:**  
Added `generation_kwargs={"max_tokens": 1024}` to the judge in `eval/deepeval_setup.py`. Metric scores and reasoning never require more than ~500–800 tokens; 1024 gives a comfortable buffer while preventing the truncation error.

---

## 9. Thresholds too low for production

**Symptom:**  
All metrics were initialised with `threshold=0.5` — the absolute minimum (equivalent to random chance for binary metrics).

**Root cause:**  
Initial implementation used the DeepEval quickstart default without adjusting for production requirements.

**Fix:**  
Raised all metric thresholds from `0.5` to `0.6` across `eval/deepeval_setup.py`. `0.6` is the recommended production floor; domain-specific GEval metrics may be raised further once baseline scores are established from real runs.

---

## 10. LangSmith env vars defined in config but never exported to `os.environ`

**Symptom:**  
LangSmith tracing fields (`langchain_tracing_v2`, `langchain_api_key`, `langchain_project`) were present in the `Settings` pydantic model in `config.py` and read correctly from `.env`, but LangSmith tracing was silently inactive — no traces appeared in the LangSmith dashboard.

**Root cause:**  
LangChain/LangSmith reads its configuration exclusively from `os.environ` at import time. Storing the values in a pydantic `Settings` object does not propagate them into the process environment, so the SDK never saw them.

**Fix:**  
Added a guarded block at the bottom of `config.py` (after `settings = Settings()`) that explicitly sets the required env vars when a key is present:
```python
if settings.langsmith_api_key:
    os.environ["LANGSMITH_TRACING"] = str(settings.langsmith_tracing).lower()
    os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
```
Also added `langsmith>=0.1.0` to `requirements.txt`.

---

## 11. LangSmith config used legacy `LANGCHAIN_` env var prefix instead of `LANGSMITH_`

**Symptom:**  
After the fix in #10, tracing was still not appearing. The env vars being set (`LANGCHAIN_API_KEY`, `LANGCHAIN_PROJECT`, `LANGCHAIN_TRACING_V2`) are the old naming convention from earlier LangChain versions.

**Root cause:**  
The modern LangSmith SDK (current as of 2025–2026) uses the `LANGSMITH_` prefix for all its env vars (`LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, `LANGSMITH_TRACING`). The `LANGCHAIN_` variants are legacy aliases that may not be honoured by newer SDK versions.

**Fix:**  
Renamed the three pydantic fields and updated the `os.environ` block in `config.py`:
- `langchain_tracing_v2` → `langsmith_tracing` (maps to `LANGSMITH_TRACING`)
- `langchain_api_key` → `langsmith_api_key` (maps to `LANGSMITH_API_KEY`)
- `langchain_project` → `langsmith_project` (maps to `LANGSMITH_PROJECT`)

`.env` should now use `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, and `LANGSMITH_TRACING`.

---

## 12. HITL API endpoints blocking the async event loop

**Symptom:**
FastAPI `/hitl/approve/{session_id}`, `/hitl/reject/{session_id}`, and `/hitl/modify/{session_id}` endpoints caused the entire Uvicorn server to freeze for the duration of graph execution (seconds to tens of seconds), preventing any other requests from being serviced during that window.

**Root cause:**
All three endpoints were declared `async def` but internally called `graph.invoke(Command(resume=...))` — the synchronous variant. Calling a blocking synchronous operation from inside an async FastAPI handler without offloading to a thread pool blocks the event loop.

**File:** `api/hitl_api.py`

**Fix:**
Replaced all three occurrences of `graph.invoke(...)` with `await graph.ainvoke(...)`.

---

## 13. `session_id` lost between HITL trigger and approve/reject in Gradio UI

**Symptom:**
The HITL approval panel (added to the chatbot) had no way to reference the suspended session — clicking Confirm or Reject did nothing because the handlers could not identify which session to resume.

**Root cause:**
`session_id` was a local variable inside the `chat_stream()` async generator, scoped to the lifetime of that generator call. Gradio event handlers (button clicks) are separate callbacks with no access to that local scope. No `gr.State()` component persisted the value across the component boundary.

**File:** `ui/chatbot.py`

**Fix:**
Added three `gr.State()` components: `session_id_state`, `proposed_actions_state`, and `hitl_pending_state`. Updated all yield sites in the renamed `chat_fn` to emit 5 outputs including these state values. Updated all `.click()` and `.submit()` wiring to match.

---

## 14. Two disconnected HITL in-memory session stores

**Symptom:**
Sessions initiated via the Gradio chatbot were invisible to the MCP `fix` tool's resume path, and vice versa. `GET /hitl/pending` only listed chatbot-initiated sessions; MCP-initiated sessions never appeared.

**Root cause:**
`api/hitl_api.py` maintained `_pending_sessions: dict` and `mcp_server/mcp_tools.py` maintained `_hitl_pending: dict` — two separate module-level dicts that were never synchronized.

**Files:** `api/hitl_api.py`, `mcp_server/mcp_tools.py`

**Fix:**
Created `api/hitl_store.py` with a thread-safe `HITLStore` singleton. Both files now import `from api.hitl_store import hitl_store` and use its `register()`, `remove()`, and `list_pending()` methods, eliminating the dual-store split.

---

## 15. No HITL approval UI in the Gradio chatbot

**Symptom:**
When the graph suspended at the HITL interrupt for a `fix`-intent query, the chatbot only showed a plain-text message with `curl` API endpoint URLs. Operators had to leave the UI and manually call the REST API.

**Root cause:**
No Gradio components for HITL interaction existed in `ui/chatbot.py`. The HITL flow was entirely REST-API-only.

**File:** `ui/chatbot.py`

**Fix:**
Added a hidden `gr.Column(visible=False) as hitl_panel` containing a `gr.CheckboxGroup` (one entry per proposed action, all pre-checked by default), a "Confirm Selections" button, and a "Reject All" button. Added `handle_approve()` and `handle_reject()` async generator handlers that call `graph.ainvoke(Command(resume=...))` directly. Panel visibility is driven reactively by `hitl_pending_state.change`.

---

## 16. `run_hitl` was a synchronous node in an async graph

**Symptom:**
Subtle compatibility risk with async checkpointers (`AsyncPostgresSaver`); inconsistent with the async invocation pattern used throughout the rest of the graph.

**Root cause:**
`run_hitl` in `agent/hitl.py` was declared as `def` (synchronous) while the graph was exclusively invoked via `graph.ainvoke` and `graph.astream`.

**File:** `agent/hitl.py`

**Fix:**
Changed `def run_hitl(state: OpsAgentState) -> dict:` to `async def run_hitl(state: OpsAgentState) -> dict:`. No body changes were required.

---

## 17. `relaunch_campaign` missing from the aggregator prompt

**Symptom:**
When a user asked to "start a campaign to drive sales recovery for Laptop Pro 15", the graph ran through HITL successfully but reported "attempts have failed." No campaign was relaunched despite the user approving.

**Root cause:**
`ACTION_TOOL_MAP` in `agent/action_executor.py` had `relaunch_campaign` registered. However, the aggregator's `AGGREGATOR_PROMPT` only listed four action types: `restock | apply_discount | pause_campaign | create_ticket`. `relaunch_campaign` was invisible to the aggregator LLM, so it invented an unrecognised action type (e.g. `launch_campaign`), which hit the `"No tool registered"` silent-failure branch and was recorded as `status="failed"`.

**File:** `agent/aggregator.py`

**Fix:**
Added `relaunch_campaign` to the `action_type` enum in the aggregator prompt and added a full "Action type reference" block documenting all five action types with their exact parameter schemas.

---

## 18. Output formatter described proposed actions as executed

**Symptom:**
For a `diagnose`-intent query ("name the products which are low on inventory"), the final response said "Restocking actions were submitted successfully to address the issue" — but no HITL had occurred and no actions had been executed.

**Root cause:**
The output formatter included `proposed_actions` in its LLM context under the label `"Proposed actions:"`. The LLM could not distinguish "proposed but not executed" from "executed" and wrote as if the actions had been carried out.

**File:** `agent/output_formatter.py`

**Fix:**
Made the context label intent-aware: `diagnose` → `"Recommended actions (NOT executed — analysis only):"`, `fix` → `"Actions pending HITL approval (NOT yet executed):"`. Also made the `explanation_prompt` intent-aware with three explicit instruction branches so the LLM knows exactly what to say based on whether it is a diagnostic, an approved fix, or a rejected fix.

---

## 19. Dead sync stub silently overriding real async `get_stockout_events`

**Symptom:**
The inventory specialist was returning hardcoded mock data (Laptop Pro 15, Mechanical Keyboard) instead of live DB results, regardless of actual database state.

**Root cause:**
`tools/inventory.py` contained leftover prototype code after the real implementation. A second `@tool def get_stockout_events` (synchronous, returning hardcoded data) was defined after the real `async def get_stockout_events`. Python last-definition-wins semantics meant the stub always took precedence. Similar stubs for `get_viewed_not_purchased` and a dangling mock `return {}` block were also present.

**File:** `tools/inventory.py`

**Fix:**
Removed all dead code: the sync `get_stockout_events` stub, the sync `get_viewed_not_purchased` stub, and the unreachable mock `return {}` block inside `get_restock_recommendations`. The file now contains only the three real async DB-backed tools.

---

## 20. Aggregator passed only compressed signal strings to the LLM — raw tool data discarded

**Symptom:**
The aggregator's LLM context contained only short signal strings like `"low inventory"`, `"reorder threshold"` — it never saw actual product names or quantities. The aggregator therefore produced generic root causes and the output formatter had nothing specific to work with.

**Root cause:**
The `findings_text` building loop in `run_aggregator` only included `f.signals` (a list of short strings compressed by the specialist's own LLM summary step). The `f.raw_tool_outputs` field — which held the actual structured DB rows — was never included in the prompt.

**File:** `agent/aggregator.py`

**Fix:**
Updated the `findings_text` building loop to also append `raw_tool_outputs` serialized as JSON (truncated at 3000 chars) under a `Raw tool data:` heading for each domain.

---

## 21. Specialist agents discarded real ToolMessage data

**Symptom:**
Even after fix #20, the aggregator's raw tool data was only the LLM's final prose summary (the text of `final_message`), not the actual structured rows returned by the DB tools.

**Root cause:**
All four specialist agents (`sales.py`, `inventory.py`, `marketing.py`, `support.py`) set:
```python
raw_tool_outputs=[{"agent_output": final_message}]
```
The `ToolMessage` objects in the ReAct agent's message history — which contained the real structured JSON from each tool call — were never extracted.

**Files:** `agent/specialists/inventory.py`, `agent/specialists/sales.py`, `agent/specialists/marketing.py`, `agent/specialists/support.py`

**Fix:**
All four specialists now iterate `result["messages"]`, extract every `ToolMessage` object, JSON-parse its content, and store those payloads in `raw_tool_outputs`. Falls back to `{"agent_output": final_message}` only if no tool messages were found.

---

## 22. Orchestrator routing "name products" queries as `fix` intent

**Symptom:**
Lookup queries such as "name the products which are low on inventory" were routed as `fix` intent, triggering HITL and causing actual restock orders to be written to the database without the user intending any action.

**Root cause:**
The `diagnose` intent definition only covered "WHY something happened (root cause analysis)." A plain lookup question didn't match "why" and the LLM defaulted to `fix`.

**File:** `agent/orchestrator.py`

**Fix:**
Updated `INTENT_ROUTING_PROMPT` so `diagnose` explicitly covers all read-only investigative queries ("what", "which", "how many", "show me", "list", "name", "identify") and is the default for any non-action query. `fix` now requires explicit corrective-action language ("fix", "restock", "apply discount", "pause", "launch a campaign").

---

## 23. Output formatter context missing specialist findings and action parameters

**Symptom:**
Final responses were generic even after fixes #20 and #21 — e.g. "Several products are currently low on inventory" rather than naming specific products with their stock counts.

**Root cause:**
`run_output_formatter` built its LLM context from only two sources: compressed `root_causes` descriptions and bare `action_type: status` strings for executed actions. The specialist findings (with real product names and quantities) and proposed action parameters were not included.

**File:** `agent/output_formatter.py`

**Fix:**
Expanded the context-building block to include all four specialist domains' `signals` and full `raw_tool_outputs` JSON (truncated at 1500 chars), proposed actions with `parameters`/`justification`/`estimated_impact`, and executed actions with `parameters` and `api_response`. Updated the `explanation_prompt` to explicitly instruct the LLM to use actual product names, quantities, and values — not vague language.
