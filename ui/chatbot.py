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
    log_text: str,
    current_session_id: str,
    current_proposed_actions: list,
    current_hitl_pending: bool,
):
    import json as _json

    if not message.strip():
        yield (
            history,
            log_text,
            current_session_id,
            current_proposed_actions,
            current_hitl_pending,
            gr.update(),
            gr.update(),
        )
        return

    session_id = str(uuid.uuid4())
    new_history = history + [{"role": "user", "content": message}]
    log_lines = [f"[session] {session_id}", f"[query] {message}", ""]

    # Initial yield: show thinking state
    yield (
        new_history + [{"role": "assistant", "content": "...thinking..."}],
        "\n".join(log_lines),
        "",
        [],
        False,
        gr.update(choices=[], value=[]),
        gr.update(),
    )

    active_nodes: dict = {}  # node -> start marker line index

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

                    if etype == "intent_classified":
                        log_lines.append(f"[intent] → {ev['intent'].upper()}")

                    elif etype == "node_start":
                        node = ev["node"]
                        label = _NODE_LABELS.get(node, node)
                        preview = ev.get("input_preview", {})
                        active_nodes[node] = len(log_lines)
                        log_lines.append(f"▶ {label}")
                        if preview:
                            for k, v in preview.items():
                                log_lines.append(f"   {k}: {v}")

                    elif etype == "node_end":
                        node = ev["node"]
                        label = _NODE_LABELS.get(node, node)
                        ms = ev.get("duration_ms", 0)
                        log_lines.append(f"✓ {label} ({ms}ms)")

                    elif etype == "tool_start":
                        tool = ev.get("tool", "?")
                        inp = ev.get("input_preview", "")
                        log_lines.append(f"   🔧 {tool}({inp[:100]})")

                    elif etype == "tool_end":
                        tool = ev.get("tool", "?")
                        out = ev.get("output_preview", "")
                        log_lines.append(f"   ✓ {tool} → {out[:120]}")

                    elif etype == "llm_start":
                        node = ev.get("node", "")
                        label = _NODE_LABELS.get(node, node)
                        log_lines.append(f"   ⚙ LLM thinking ({label})...")

                    elif etype == "llm_end":
                        tokens = ev.get("tokens", {})
                        if tokens:
                            log_lines.append("   ✓ LLM done — in:{tokens.get('input',0)} out:{tokens.get('output',0)} tokens")
                        else:
                            log_lines.append("   ✓ LLM done")

                    elif etype == "interrupt":
                        proposed_actions = ev.get("proposed_actions", [])
                        sid = ev.get("session_id", session_id)
                        hitl_store.register(sid, proposed_actions)
                        log_lines.append("")
                        log_lines.append("⏸ Graph suspended — awaiting human approval")
                        final_answer = (
                            f"⏸ **Human approval required.**\n\n"
                            f"**{len(proposed_actions)} action(s) proposed.** "
                            f"Review and approve or reject them in the panel below."
                        )
                        choices, default_value = _build_action_labels(proposed_actions)
                        yield (
                            new_history + [{"role": "assistant", "content": final_answer}],
                            "\n".join(log_lines),
                            sid,
                            proposed_actions,
                            True,
                            gr.update(choices=choices, value=default_value),
                            gr.update(value=f"## ⏸ Action Required\n\n**{len(proposed_actions)} action(s) are pending your approval.** Review the checkboxes below."),
                        )
                        return

                    elif etype == "result":
                        log_lines.append("")
                        log_lines.append("✅ Graph completed")
                        final_answer = ev.get("finding") or ev.get("result") or str(ev)
                        yield (
                            new_history + [{"role": "assistant", "content": final_answer}],
                            "\n".join(log_lines),
                            "",
                            [],
                            False,
                            gr.update(choices=[], value=[]),
                            gr.update(value="*No pending approvals.*"),
                        )
                        return

                    elif etype == "error":
                        log_lines.append("")
                        log_lines.append(f"❌ Error: {ev.get('message', 'unknown')}")
                        yield (
                            new_history + [{"role": "assistant", "content": f"Error: {ev.get('message')}"}],
                            "\n".join(log_lines),
                            "",
                            [],
                            False,
                            gr.update(choices=[], value=[]),
                            gr.update(value="*No pending approvals.*"),
                        )
                        return

                    # Non-terminal events: yield a live log update
                    yield (
                        new_history + [{"role": "assistant", "content": "...thinking..."}],
                        "\n".join(log_lines),
                        "",
                        [],
                        False,
                        gr.update(),
                        gr.update(),
                    )

    except Exception as e:
        import traceback
        log_lines.append(f"\n--- STREAM ERROR ---\n{traceback.format_exc()}")
        yield (
            new_history + [{"role": "assistant", "content": f"Error: {e}"}],
            "\n".join(log_lines),
            "",
            [],
            False,
            gr.update(choices=[], value=[]),
            gr.update(value="*No pending approvals.*"),
        )
        return

    # Stream ended without a terminal event
    yield (
        new_history + [{"role": "assistant", "content": "No response received."}],
        "\n".join(log_lines),
        "",
        [],
        False,
        gr.update(choices=[], value=[]),
        gr.update(value="*No pending approvals.*"),
    )


async def handle_approve(
    session_id: str,
    proposed_actions: list,
    selected_labels: list,
    history: list,
    log_text: str,
):
    if not session_id:
        yield history, log_text, "", [], False, gr.update(choices=[], value=[]), gr.update()
        return

    # Rebuild label → action mapping
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
        log_lines.append(f"[hitl] {final_text}")
        new_history = new_history + [{"role": "assistant", "content": final_text}]

    except Exception as e:
        import traceback
        log_lines.append(f"\n--- APPROVE ERROR ---\n{traceback.format_exc()}")
        new_history = new_history + [
            {"role": "assistant", "content": f"Error approving: {e}"}
        ]

    yield (
        new_history,
        "\n".join(log_lines),
        "",
        [],
        False,
        gr.update(choices=[], value=[]),
        gr.update(value="*No pending approvals. Actions were executed.*"),
    )


async def handle_reject(
    session_id: str,
    history: list,
    log_text: str,
):
    if not session_id:
        yield history, log_text, "", [], False, gr.update(choices=[], value=[]), gr.update()
        return

    config = {"configurable": {"thread_id": session_id}}
    log_lines = [log_text, "", "[hitl] Operator rejected all proposed actions."]
    new_history = history + [
        {"role": "user", "content": "❌ Rejected all proposed actions."}
    ]

    try:
        base_url = f"http://localhost:{settings.app_server_port}"
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{base_url}/hitl/reject/{session_id}",
                json={},
            )
            resp.raise_for_status()
            data = resp.json()

        hitl_store.remove(session_id)
        final_text = data.get("message", "All proposed actions were rejected. No changes were made.")
        log_lines.append("[hitl] All actions rejected — no mutations applied.")
        new_history = new_history + [{"role": "assistant", "content": final_text}]

    except Exception as e:
        import traceback
        log_lines.append(f"\n--- REJECT ERROR ---\n{traceback.format_exc()}")
        new_history = new_history + [
            {"role": "assistant", "content": f"Error rejecting: {e}"}
        ]

    yield (
        new_history,
        "\n".join(log_lines),
        "",
        [],
        False,
        gr.update(choices=[], value=[]),
        gr.update(value="*No pending approvals. Actions were rejected.*"),
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

        # ── Tab 2: Approvals ──────────────────────────────────────────────
        with gr.Tab("⏸ Approvals"):
            approval_status = gr.Markdown("*No pending approvals.*")
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

    # ── Chat submission ───────────────────────────────────────────────────
    send_btn.click(
        fn=chat_fn,
        inputs=[msg_box, chatbot, log_box, session_id_state, proposed_actions_state, hitl_pending_state],
        outputs=[chatbot, log_box, session_id_state, proposed_actions_state, hitl_pending_state, action_checkbox_group, approval_status],
    ).then(lambda: "", outputs=msg_box)

    msg_box.submit(
        fn=chat_fn,
        inputs=[msg_box, chatbot, log_box, session_id_state, proposed_actions_state, hitl_pending_state],
        outputs=[chatbot, log_box, session_id_state, proposed_actions_state, hitl_pending_state, action_checkbox_group, approval_status],
    ).then(lambda: "", outputs=msg_box)

    clear_btn.click(
        fn=lambda: ([], "Waiting for query...", "", [], False),
        outputs=[chatbot, log_box, session_id_state, proposed_actions_state, hitl_pending_state],
    )

    # ── HITL buttons ──────────────────────────────────────────────────────
    confirm_btn.click(
        fn=handle_approve,
        inputs=[session_id_state, proposed_actions_state, action_checkbox_group, chatbot, log_box],
        outputs=[chatbot, log_box, session_id_state, proposed_actions_state, hitl_pending_state, action_checkbox_group, approval_status],
    )

    reject_btn.click(
        fn=handle_reject,
        inputs=[session_id_state, chatbot, log_box],
        outputs=[chatbot, log_box, session_id_state, proposed_actions_state, hitl_pending_state, action_checkbox_group, approval_status],
    )


if __name__ == "__main__":
    # When run directly (not via api/app.py), launch standalone for development
    demo.launch(server_name="0.0.0.0", server_port=7860, share=False)
