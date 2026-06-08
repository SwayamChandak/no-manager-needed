"""
ui/chatbot.py — Gradio chatbot UI for the E-Commerce Ops Agent.

Streams graph node updates and displays them in a live log panel.
Includes a HITL approval panel for fix-intent queries: when the graph suspends
at the hitl_node interrupt(), a panel appears with per-action checkboxes so
the operator can approve a subset or reject all — without leaving the UI.

Run via:
    python main.py --mode chat
"""

import uuid
from datetime import datetime

import gradio as gr
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from agent.graph import graph
from api.hitl_store import hitl_store


def _build_initial_state(query: str, session_id: str) -> dict:
    return {
        "session_id": session_id,
        "user_query": query,
        "intent": "diagnose",  # orchestrator will override
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


def _build_action_labels(proposed_actions: list) -> tuple[list[str], list[str]]:
    """Convert proposed_actions dicts to (choices, default_selected) for CheckboxGroup.

    All actions are pre-selected by default (operator unchecks to exclude).
    """
    labels = []
    for i, action in enumerate(proposed_actions):
        action_type = action.get("action_type", f"action_{i}")
        impact = action.get("estimated_impact", "")
        justification = action.get("justification", "")
        label = f"{action_type} | Impact: {impact} | {justification[:80]}"
        labels.append(label)
    return labels, labels  # (choices, all pre-selected)


def _on_hitl_state_change(proposed_actions: list, hitl_pending: bool):
    """Reactively update the CheckboxGroup choices and HITL panel visibility.

    Called automatically by Gradio when hitl_pending_state changes.
    """
    if hitl_pending and proposed_actions:
        choices, default_value = _build_action_labels(proposed_actions)
        return (
            gr.update(choices=choices, value=default_value),
            gr.update(visible=True),
        )
    return (
        gr.update(choices=[], value=[]),
        gr.update(visible=False),
    )


async def chat_fn(
    message: str,
    history: list,
    log_text: str,
    current_session_id: str,
    current_proposed_actions: list,
    current_hitl_pending: bool,
):
    """Async generator that streams graph execution updates to the Gradio UI.

    Yields 5 outputs on every code path:
        (chatbot_history, log_text, session_id_state, proposed_actions_state, hitl_pending_state)

    When the graph suspends at the HITL interrupt, the last three outputs are
    populated with the suspended session's data, causing the HITL panel to appear.
    """
    if not message.strip():
        yield (
            history,
            log_text,
            current_session_id,
            current_proposed_actions,
            current_hitl_pending,
        )
        return

    session_id = str(uuid.uuid4())
    initial_state = _build_initial_state(message, session_id)
    config = {"configurable": {"thread_id": session_id}}

    log_lines = [f"[session] {session_id}", f"[query] {message}", ""]
    final_answer = ""

    new_history = history + [{"role": "user", "content": message}]

    try:
        async for update in graph.astream(initial_state, config=config, stream_mode="updates"):
            for node_name, node_output in update.items():
                log_lines.append(f"{'─'*60}")
                log_lines.append(f"▶ [{node_name}]")

                if isinstance(node_output, dict):
                    import json as _json

                    fr = node_output.get("final_response")
                    if fr is not None:
                        final_answer = getattr(fr, "explanation", None) or str(fr)

                    # --- tool_call_log: show each node's metadata ---
                    tool_calls = node_output.get("tool_call_log")
                    if tool_calls:
                        for call in tool_calls:
                            if isinstance(call, dict):
                                # Pretty-print the call metadata, excluding verbose keys
                                display = {k: v for k, v in call.items() if k not in ("timestamp",)}
                                log_lines.append(f"  metadata: {_json.dumps(display, default=str)}")

                    # --- Specialist findings: show signals + raw tool outputs ---
                    for domain in ("sales", "inventory", "marketing", "support"):
                        finding_key = f"{domain}_findings"
                        finding = node_output.get(finding_key)
                        if finding is not None:
                            log_lines.append(f"  [{domain} finding]")
                            signals = getattr(finding, "signals", [])
                            if signals:
                                for sig in signals:
                                    log_lines.append(f"    signal: {sig}")
                            raw = getattr(finding, "raw_tool_outputs", [])
                            for i, output in enumerate(raw):
                                if isinstance(output, dict):
                                    raw_str = _json.dumps(output, default=str)
                                    if len(raw_str) > 800:
                                        raw_str = raw_str[:800] + "... [truncated]"
                                    log_lines.append(f"    tool output [{i+1}]: {raw_str}")

                    # --- Root causes ---
                    root_causes = node_output.get("root_causes")
                    if root_causes:
                        log_lines.append(f"  root causes ({len(root_causes)}):")
                        for rc in root_causes:
                            desc = getattr(rc, "description", str(rc))
                            conf = getattr(rc, "confidence", "?")
                            log_lines.append(f"    • {desc} (confidence: {conf:.0%})" if isinstance(conf, float) else f"    • {desc}")

                    # --- Proposed actions (aggregator output) ---
                    proposed = node_output.get("proposed_actions")
                    if proposed:
                        log_lines.append(f"  proposed actions ({len(proposed)}):")
                        for pa in proposed:
                            atype = getattr(pa, "action_type", pa.get("action_type", "?") if isinstance(pa, dict) else "?")
                            params = getattr(pa, "parameters", pa.get("parameters", "{}") if isinstance(pa, dict) else "{}")
                            justification = getattr(pa, "justification", pa.get("justification", "") if isinstance(pa, dict) else "")
                            log_lines.append(f"    • {atype}: {params}")
                            if justification:
                                log_lines.append(f"      reason: {justification[:120]}")

                    # --- Executed actions ---
                    executed = node_output.get("executed_actions")
                    if executed:
                        log_lines.append(f"  executed actions ({len(executed)}):")
                        for ea in executed:
                            atype = getattr(ea, "action_type", "?")
                            status = getattr(ea, "status", "?")
                            api_resp = getattr(ea, "api_response", {}) or {}
                            log_lines.append(f"    • {atype}: {status}")
                            if api_resp:
                                resp_str = _json.dumps(api_resp, default=str)
                                if len(resp_str) > 300:
                                    resp_str = resp_str[:300] + "..."
                                log_lines.append(f"      response: {resp_str}")

                    # --- Correlation matrix (aggregator) ---
                    corr = node_output.get("correlation_matrix")
                    if corr:
                        log_lines.append("  correlation matrix:")
                        if isinstance(corr, dict):
                            for pair, detail in corr.items():
                                if isinstance(detail, dict) and detail.get("linked"):
                                    log_lines.append(f"    {pair}: linked — {detail.get('explanation', '')[:100]}")

            # Mid-stream yield — HITL state unchanged
            yield (
                new_history + [{"role": "assistant", "content": "...thinking..."}],
                "\n".join(log_lines),
                "",
                [],
                False,
            )

    except Exception as e:
        import traceback

        log_lines.append(f"\n--- ERROR ---\n{traceback.format_exc()}")
        final_answer = f"Error: {e}"
        yield (
            new_history + [{"role": "assistant", "content": final_answer}],
            "\n".join(log_lines),
            "",
            [],
            False,
        )
        return

    # Check if the graph suspended at the HITL interrupt checkpoint
    proposed_dicts: list = []
    hitl_triggered = False
    try:
        snapshot = graph.get_state(config)
        if snapshot and snapshot.next:
            proposed = snapshot.values.get("proposed_actions", [])
            proposed_dicts = [
                a.model_dump() if hasattr(a, "model_dump") else a for a in proposed
            ]
            hitl_store.register(session_id, proposed_dicts)
            hitl_triggered = True
            final_answer = (
                f"⏸ **Human approval required.**\n\n"
                f"**{len(proposed_dicts)} action(s) proposed.** "
                f"Review and approve or reject them in the panel below."
            )
    except Exception:
        pass  # If state check fails, fall through to normal final_answer handling

    if not final_answer:
        final_answer = "Agent completed but produced no final response."

    # Final yield — populate HITL state if interrupt was detected
    yield (
        new_history + [{"role": "assistant", "content": final_answer}],
        "\n".join(log_lines),
        session_id if hitl_triggered else "",
        proposed_dicts if hitl_triggered else [],
        hitl_triggered,
    )


async def handle_approve(
    session_id: str,
    proposed_actions: list,
    selected_labels: list,
    history: list,
    log_text: str,
):
    """Called when the operator clicks 'Confirm Selections'.

    Filters proposed_actions to only those whose generated label appears in
    selected_labels, then resumes the suspended graph with approved=True.

    Yields 6 outputs:
        (chatbot_history, log_text, session_id_state, proposed_actions_state,
         hitl_pending_state, hitl_panel)
    """
    if not session_id:
        yield history, log_text, "", [], False, gr.update(visible=False)
        return

    config = {"configurable": {"thread_id": session_id}}

    # Rebuild label → action mapping using the same format as _build_action_labels
    label_to_action: dict = {}
    for i, action in enumerate(proposed_actions):
        action_type = action.get("action_type", f"action_{i}")
        impact = action.get("estimated_impact", "")
        justification = action.get("justification", "")
        label = f"{action_type} | Impact: {impact} | {justification[:80]}"
        label_to_action[label] = action

    filtered_actions = [
        label_to_action[lbl] for lbl in selected_labels if lbl in label_to_action
    ]

    log_lines = [
        log_text,
        "",
        f"[hitl] Operator approved {len(filtered_actions)} of {len(proposed_actions)} action(s).",
    ]
    new_history = history + [
        {"role": "user", "content": f"✅ Approved {len(filtered_actions)} action(s)."}
    ]

    try:
        result = await graph.ainvoke(
            Command(resume={"approved": True, "modified_actions": filtered_actions or None}),
            config=config,
        )
        hitl_store.remove(session_id)

        final_response = result.get("final_response")
        executed = result.get("executed_actions", [])
        final_text = (
            getattr(final_response, "explanation", None) or str(final_response)
            if final_response
            else f"Executed {len(executed)} action(s) successfully."
        )
        log_lines.append(f"[action_executor] {len(executed)} action(s) executed.")
        new_history = new_history + [{"role": "assistant", "content": final_text}]

    except Exception as e:
        import traceback

        log_lines.append(f"\n--- APPROVE ERROR ---\n{traceback.format_exc()}")
        new_history = new_history + [
            {"role": "assistant", "content": f"Error resuming graph: {e}"}
        ]

    yield (
        new_history,
        "\n".join(log_lines),
        "",
        [],
        False,
        gr.update(visible=False),
    )


async def handle_reject(
    session_id: str,
    history: list,
    log_text: str,
):
    """Called when the operator clicks 'Reject All'.

    Resumes the suspended graph with approved=False. The action_executor_node
    skips all actions and the output_formatter returns a rejection response.

    Yields 6 outputs:
        (chatbot_history, log_text, session_id_state, proposed_actions_state,
         hitl_pending_state, hitl_panel)
    """
    if not session_id:
        yield history, log_text, "", [], False, gr.update(visible=False)
        return

    config = {"configurable": {"thread_id": session_id}}
    log_lines = [log_text, "", "[hitl] Operator rejected all proposed actions."]
    new_history = history + [
        {"role": "user", "content": "❌ Rejected all proposed actions."}
    ]

    try:
        result = await graph.ainvoke(
            Command(resume={"approved": False}),
            config=config,
        )
        hitl_store.remove(session_id)

        final_response = result.get("final_response")
        final_text = (
            getattr(final_response, "explanation", None) or str(final_response)
            if final_response
            else "All proposed actions were rejected. No changes were made."
        )
        log_lines.append("[action_executor] All actions rejected — no mutations applied.")
        new_history = new_history + [{"role": "assistant", "content": final_text}]

    except Exception as e:
        import traceback

        log_lines.append(f"\n--- REJECT ERROR ---\n{traceback.format_exc()}")
        new_history = new_history + [
            {"role": "assistant", "content": f"Error resuming graph: {e}"}
        ]

    yield (
        new_history,
        "\n".join(log_lines),
        "",
        [],
        False,
        gr.update(visible=False),
    )


# ---------------------------------------------------------------------------
# Gradio layout
# ---------------------------------------------------------------------------

with gr.Blocks(title="E-Commerce Ops Agent", theme=gr.themes.Soft()) as demo:
    gr.Markdown("# E-Commerce Ops Agent\nAsk about sales, inventory, marketing, or support issues.")

    # ---- HITL session state (persisted across event callback boundaries) ----
    session_id_state = gr.State(value="")
    proposed_actions_state = gr.State(value=[])
    hitl_pending_state = gr.State(value=False)

    # ---- Main chat layout ----
    with gr.Row():
        with gr.Column(scale=2):
            chatbot = gr.Chatbot(height=500, label="Agent Chat")
            with gr.Row():
                msg_box = gr.Textbox(
                    placeholder="Ask about your e-commerce operations...",
                    scale=4,
                    label="",
                )
                send_btn = gr.Button("Send", variant="primary", scale=1)
            clear_btn = gr.Button("Clear", variant="secondary")

        with gr.Column(scale=1):
            log_box = gr.Textbox(
                label="Agent Execution Log",
                lines=30,
                interactive=False,
                value="Waiting for query...",
                max_lines=50,
            )

    # ---- HITL Approval Panel — hidden by default, revealed on interrupt ----
    with gr.Column(visible=False) as hitl_panel:
        gr.Markdown("## ⏸ Human Approval Required")
        gr.Markdown(
            "The agent has proposed the following actions. "
            "**Uncheck any you want to skip**, then click **Confirm Selections**. "
            "Or click **Reject All** to cancel without making any changes."
        )
        action_checkbox_group = gr.CheckboxGroup(
            choices=[],
            value=[],
            label="Proposed Actions — uncheck to exclude from execution",
            interactive=True,
        )
        with gr.Row():
            confirm_btn = gr.Button("✅ Confirm Selections", variant="primary")
            reject_btn = gr.Button("❌ Reject All", variant="stop")

    # ---- Reactive: update checkbox choices and panel visibility when HITL state changes ----
    hitl_pending_state.change(
        fn=_on_hitl_state_change,
        inputs=[proposed_actions_state, hitl_pending_state],
        outputs=[action_checkbox_group, hitl_panel],
    )

    # ---- Chat submission wiring ----
    send_btn.click(
        fn=chat_fn,
        inputs=[msg_box, chatbot, log_box, session_id_state, proposed_actions_state, hitl_pending_state],
        outputs=[chatbot, log_box, session_id_state, proposed_actions_state, hitl_pending_state],
    ).then(lambda: "", outputs=msg_box)

    msg_box.submit(
        fn=chat_fn,
        inputs=[msg_box, chatbot, log_box, session_id_state, proposed_actions_state, hitl_pending_state],
        outputs=[chatbot, log_box, session_id_state, proposed_actions_state, hitl_pending_state],
    ).then(lambda: "", outputs=msg_box)

    # ---- Clear button resets all state including HITL ----
    clear_btn.click(
        fn=lambda: ([], "Waiting for query...", "", [], False),
        outputs=[chatbot, log_box, session_id_state, proposed_actions_state, hitl_pending_state],
    )

    # ---- HITL approval buttons ----
    confirm_btn.click(
        fn=handle_approve,
        inputs=[session_id_state, proposed_actions_state, action_checkbox_group, chatbot, log_box],
        outputs=[chatbot, log_box, session_id_state, proposed_actions_state, hitl_pending_state, hitl_panel],
    )

    reject_btn.click(
        fn=handle_reject,
        inputs=[session_id_state, chatbot, log_box],
        outputs=[chatbot, log_box, session_id_state, proposed_actions_state, hitl_pending_state, hitl_panel],
    )


if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860, share=False)
