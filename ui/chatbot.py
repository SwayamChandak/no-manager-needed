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

import gradio as gr
import httpx

from config import settings
from api.hitl_store import hitl_store

_NODE_LABELS = {
    "orchestrator_node":    "🧠 Orchestrator",
    "sales_node":           "💰 Sales Specialist",
    "inventory_node":       "📦 Inventory Specialist",
    "marketing_node":       "📣 Marketing Specialist",
    "support_node":         "🎧 Support Specialist",
    "aggregator_node":      "🔗 Aggregator",
    "reflection_node":      "🔍 Reflection",
    "hitl_node":            "⏸ HITL Checkpoint",
    "action_executor_node": "⚡ Action Executor",
    "memory_writer_node":   "💾 Memory Writer",
    "output_formatter_node": "📝 Output Formatter",
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



async def chat_fn(
    message: str,
    history: list,
    current_session_id: str,
    current_proposed_actions: list,
    current_hitl_pending: bool,
):
    import json as _json

    if not message.strip():
        yield (
            history,
            current_session_id,
            current_proposed_actions,
            current_hitl_pending,
            gr.update(),
            gr.update(),
            gr.update(),
        )
        return

    session_id = str(uuid.uuid4())
    new_history = history + [{"role": "user", "content": message}]
    log_lines: list[str] = []

    yield (
        new_history + [{"role": "assistant", "content": "...thinking..."}],
        "",
        [],
        False,
        gr.update(choices=[], value=[]),
        gr.update(),
        gr.update(value=""),
    )

    try:
        base_url = f"http://localhost:{settings.app_server_port}"
        async with httpx.AsyncClient(timeout=180.0) as client:
            async with client.stream(
                "POST",
                f"{base_url}/chat/stream",
                json={
                    "message": message,
                    "session_id": session_id,
                    "intent": "auto",
                },
                timeout=180.0,
            ) as response:
                response.raise_for_status()
                async for raw_line in response.aiter_lines():
                    if not raw_line.startswith("data: "):
                        continue
                    try:
                        ev = _json.loads(raw_line[6:])
                    except Exception:
                        continue

                    etype = ev.get("type", "")

                    # ── Live log: events the backend actually emits ──────────────
                    # intent_classified → emitted for all intents.
                    # node_start / node_end → emitted only for the recall path.
                    # tool_start / tool_end / llm_start / llm_end are listed in the
                    # backend docstring but are NOT currently emitted; diagnose, fix,
                    # and summarize block on a single ainvoke() with no intermediate
                    # events, so the log will only show the intent line for those.
                    if etype == "intent_classified":
                        log_lines.append(f"🎯 Intent: {ev.get('intent', '?')}")
                        yield (
                            new_history + [{"role": "assistant", "content": "...thinking..."}],
                            "",
                            [],
                            False,
                            gr.update(choices=[], value=[]),
                            gr.update(),
                            gr.update(value="\n".join(log_lines)),
                        )
                        continue

                    elif etype == "node_start":
                        node = ev.get("node", "")
                        label = _NODE_LABELS.get(node, node)
                        log_lines.append(f"▶ {label}…")
                        yield (
                            new_history + [{"role": "assistant", "content": "...thinking..."}],
                            "",
                            [],
                            False,
                            gr.update(choices=[], value=[]),
                            gr.update(),
                            gr.update(value="\n".join(log_lines)),
                        )
                        continue

                    elif etype == "node_end":
                        node = ev.get("node", "")
                        label = _NODE_LABELS.get(node, node)
                        ms = ev.get("duration_ms", "")
                        pending = f"▶ {label}…"
                        if log_lines and log_lines[-1] == pending:
                            log_lines[-1] = f"✓ {label} ({ms}ms)"
                        else:
                            log_lines.append(f"✓ {label} ({ms}ms)")
                        yield (
                            new_history + [{"role": "assistant", "content": "...thinking..."}],
                            "",
                            [],
                            False,
                            gr.update(choices=[], value=[]),
                            gr.update(),
                            gr.update(value="\n".join(log_lines)),
                        )
                        continue

                    elif etype == "off_topic":
                        rejection_msg = ev.get("message", "I can only help with e-commerce operations topics.")
                        off_topic_reply = (
                            f"Out of scope\n\n"
                            f"{rejection_msg}\n\n"
                            f"I can help you with:\n"
                            f"Sales: revenue drops, order trends, product performance\n"
                            f"Inventory: stock levels, stockouts, restock decisions\n"
                            f"Marketing: campaign performance, promotions, ad spend\n"
                            f"Support: customer complaints, ticket trends, refunds\n\n"
                            f'Try asking: "Why did sales drop yesterday?" or "Which products are low on stock?"'
                        )
                        yield (
                            new_history + [{"role": "assistant", "content": off_topic_reply}],
                            "",
                            [],
                            False,
                            gr.update(choices=[], value=[]),
                            gr.update(value="No pending approvals."),
                            gr.update(value="\n".join(log_lines)),
                        )
                        return

                    elif etype == "interrupt":
                        proposed_actions = ev.get("proposed_actions", [])
                        sid = ev.get("session_id", session_id)
                        hitl_store.register(sid, proposed_actions)
                        final_answer = (
                            f"Human approval required.\n\n"
                            f"{len(proposed_actions)} action(s) proposed. "
                            f"Review and approve or reject them in the Approvals tab."
                        )
                        choices, default_value = _build_action_labels(proposed_actions)
                        yield (
                            new_history + [{"role": "assistant", "content": final_answer}],
                            sid,
                            proposed_actions,
                            True,
                            gr.update(choices=choices, value=default_value),
                            gr.update(value=f"{len(proposed_actions)} action(s) are pending your approval. Review the checkboxes below."),
                            gr.update(value="\n".join(log_lines)),
                        )
                        return

                    elif etype == "result":
                        final_answer = ev.get("finding") or ev.get("result") or ""
                        yield (
                            new_history + [{"role": "assistant", "content": final_answer}],
                            "",
                            [],
                            False,
                            gr.update(choices=[], value=[]),
                            gr.update(value="No pending approvals."),
                            gr.update(value="\n".join(log_lines)),
                        )
                        return

                    elif etype == "error":
                        yield (
                            new_history + [{"role": "assistant", "content": f"Error: {ev.get('message')}"}],
                            "",
                            [],
                            False,
                            gr.update(choices=[], value=[]),
                            gr.update(value="No pending approvals."),
                            gr.update(value="\n".join(log_lines)),
                        )
                        return

    except Exception as e:
        yield (
            new_history + [{"role": "assistant", "content": f"Error: {e}"}],
            "",
            [],
            False,
            gr.update(choices=[], value=[]),
            gr.update(value="No pending approvals."),
            gr.update(),
        )
        return

    yield (
        new_history + [{"role": "assistant", "content": "No response received."}],
        "",
        [],
        False,
        gr.update(choices=[], value=[]),
        gr.update(value="No pending approvals."),
        gr.update(),
    )


async def handle_approve(
    session_id: str,
    proposed_actions: list,
    selected_labels: list,
    history: list,
):
    if not session_id:
        yield history, "", [], False, gr.update(choices=[], value=[]), gr.update()
        return

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

    new_history = history + [
        {"role": "user", "content": f"✅ Approved {len(filtered_actions)} action(s)."}
    ]

    try:
        base_url = f"http://localhost:{settings.app_server_port}"
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{base_url}/hitl/approve/{session_id}",
                json={"modified_actions": filtered_actions or None},
            )
            resp.raise_for_status()
            data = resp.json()

        hitl_store.remove(session_id)
        final_text = data.get("message", "Actions approved and executed successfully.")
        new_history = new_history + [{"role": "assistant", "content": final_text}]

    except Exception as e:
        new_history = new_history + [
            {"role": "assistant", "content": f"Error approving: {e}"}
        ]

    yield (
        new_history,
        "",
        [],
        False,
        gr.update(choices=[], value=[]),
        gr.update(value="No pending approvals. Actions were executed."),
        gr.update(value=""),
    )


async def handle_reject(
    session_id: str,
    history: list,
    rejection_reason: str,
):
    if not session_id:
        yield history, "", [], False, gr.update(choices=[], value=[]), gr.update(), gr.update()
        return

    reason_display = rejection_reason.strip() if rejection_reason and rejection_reason.strip() else "No reason provided."
    new_history = history + [
        {"role": "user", "content": f"❌ Rejected all proposed actions. Reason: {reason_display}"}
    ]

    try:
        base_url = f"http://localhost:{settings.app_server_port}"
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{base_url}/hitl/reject/{session_id}",
                json={"reason": rejection_reason.strip() if rejection_reason else None},
            )
            resp.raise_for_status()
            data = resp.json()

        hitl_store.remove(session_id)
        final_text = data.get("message", "All proposed actions were rejected. No changes were made.")
        new_history = new_history + [{"role": "assistant", "content": final_text}]

    except Exception as e:
        new_history = new_history + [
            {"role": "assistant", "content": f"Error rejecting: {e}"}
        ]

    yield (
        new_history,
        "",
        [],
        False,
        gr.update(choices=[], value=[]),
        gr.update(value="No pending approvals. Actions were rejected."),
        gr.update(value=""),
    )


# ---------------------------------------------------------------------------
# Gradio layout
# ---------------------------------------------------------------------------

with gr.Blocks(title="E-Commerce Ops Agent", theme=gr.themes.Soft()) as demo:
    gr.Markdown("# E-Commerce Ops Agent\nAsk about sales, inventory, marketing, or support issues.")

    session_id_state = gr.State(value="")
    proposed_actions_state = gr.State(value=[])
    hitl_pending_state = gr.State(value=False)

    with gr.Tabs():
        # ── Tab 1: Chat ───────────────────────────────────────────────────
        with gr.Tab("💬 Chat"):
            chatbot = gr.Chatbot(
                height=500,
                label="Agent Chat",
                latex_delimiters=[],
                render_markdown=False,
            )
            with gr.Row():
                msg_box = gr.Textbox(
                    placeholder="Ask about your e-commerce operations...",
                    scale=4,
                    label="",
                )
                send_btn = gr.Button("Send", variant="primary", scale=1)
            clear_btn = gr.Button("Clear", variant="secondary")
            live_log_box = gr.Textbox(
                label="Agent Activity Log",
                lines=4,
                max_lines=8,
                interactive=False,
                placeholder="Agent steps will appear here during processing...",
            )

        # ── Tab 2: Approvals ──────────────────────────────────────────────
        with gr.Tab("⏸ Approvals"):
            approval_status = gr.Markdown("No pending approvals.")
            gr.Markdown(
                "The agent has proposed the following actions. "
                "Uncheck any you want to skip, then click Confirm Selections. "
                "Or click Reject All to cancel without making any changes."
            )
            action_checkbox_group = gr.CheckboxGroup(
                choices=[],
                value=[],
                label="Proposed Actions — uncheck to exclude from execution",
                interactive=True,
            )
            rejection_reason_box = gr.Textbox(
                label="Rejection Reason (required when rejecting)",
                placeholder="Explain why you are rejecting these actions...",
                lines=2,
                interactive=True,
            )
            with gr.Row():
                confirm_btn = gr.Button("✅ Confirm Selections", variant="primary")
                reject_btn = gr.Button("❌ Reject All", variant="stop")

    # ── Chat submission ───────────────────────────────────────────────────
    send_btn.click(
        fn=chat_fn,
        inputs=[msg_box, chatbot, session_id_state, proposed_actions_state, hitl_pending_state],
        outputs=[chatbot, session_id_state, proposed_actions_state, hitl_pending_state, action_checkbox_group, approval_status, live_log_box],
    ).then(lambda: "", outputs=msg_box)

    msg_box.submit(
        fn=chat_fn,
        inputs=[msg_box, chatbot, session_id_state, proposed_actions_state, hitl_pending_state],
        outputs=[chatbot, session_id_state, proposed_actions_state, hitl_pending_state, action_checkbox_group, approval_status, live_log_box],
    ).then(lambda: "", outputs=msg_box)

    clear_btn.click(
        fn=lambda: ([], "", [], False, ""),
        outputs=[chatbot, session_id_state, proposed_actions_state, hitl_pending_state, live_log_box],
    )

    # ── HITL buttons ──────────────────────────────────────────────────────
    confirm_btn.click(
        fn=handle_approve,
        inputs=[session_id_state, proposed_actions_state, action_checkbox_group, chatbot],
        outputs=[chatbot, session_id_state, proposed_actions_state, hitl_pending_state, action_checkbox_group, approval_status, rejection_reason_box],
    )

    reject_btn.click(
        fn=handle_reject,
        inputs=[session_id_state, chatbot, rejection_reason_box],
        outputs=[chatbot, session_id_state, proposed_actions_state, hitl_pending_state, action_checkbox_group, approval_status, rejection_reason_box],
    )


if __name__ == "__main__":
    # When run directly (not via api/app.py), launch standalone for development
    demo.launch(server_name="0.0.0.0", server_port=7860, share=False, theme=gr.themes.Soft())
