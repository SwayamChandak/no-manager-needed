"""
ui/chatbot.py — Gradio chatbot UI for the E-Commerce Ops Agent.

Streams graph node updates and displays them in a live log panel.

Run via:
    python main.py --mode chat
"""

import uuid
from datetime import datetime

import gradio as gr
from langchain_core.messages import HumanMessage

from agent.graph import graph
from api.hitl_api import register_pending_session


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


async def chat_stream(message: str, history: list, log_text: str):
    """Async generator that streams graph execution updates to the Gradio UI.

    history is a list of {"role": "user"|"assistant", "content": str} dicts.
    We append the user message + assistant reply on each turn.
    """
    if not message.strip():
        yield history, log_text
        return

    session_id = str(uuid.uuid4())
    initial_state = _build_initial_state(message, session_id)
    config = {"configurable": {"thread_id": session_id}}

    log_lines = [f"[session] {session_id}", f"[query] {message}", ""]
    final_answer = ""

    # Add user message to history immediately
    new_history = history + [{"role": "user", "content": message}]

    try:
        async for update in graph.astream(initial_state, config=config, stream_mode="updates"):
            for node_name, node_output in update.items():
                log_lines.append(f"[{node_name}] completed")

                if isinstance(node_output, dict):
                    fr = node_output.get("final_response")
                    if fr is not None:
                        final_answer = getattr(fr, "explanation", None) or str(fr)

                    root_causes = node_output.get("root_causes")
                    if root_causes:
                        log_lines.append(f"  Root causes found: {len(root_causes)}")

                    tool_calls = node_output.get("tool_call_log")
                    if tool_calls:
                        for call in tool_calls[-3:]:
                            log_lines.append(f"  Tool: {call}")

            # Show thinking state after each node
            yield (
                new_history + [{"role": "assistant", "content": "...thinking..."}],
                "\n".join(log_lines),
            )

    except Exception as e:
        import traceback

        tb = traceback.format_exc()
        log_lines.append(f"\n--- ERROR ---\n{tb}")
        final_answer = f"Error: {e}"
        yield (
            new_history + [{"role": "assistant", "content": final_answer}],
            "\n".join(log_lines),
        )
        return

    # Check if the graph is suspended at an interrupt (HITL checkpoint)
    try:
        snapshot = graph.get_state(config)
        if snapshot and snapshot.next:
            # Graph is paused — register this session for the HITL API
            proposed = snapshot.values.get("proposed_actions", [])
            proposed_dicts = [
                a.model_dump() if hasattr(a, "model_dump") else a
                for a in proposed
            ]
            register_pending_session(session_id, proposed_dicts)

            actions_text = "\n".join(
                f"  - **{a.get('action_type', 'action')}**: {a.get('justification', '')}"
                for a in proposed_dicts
            )
            final_answer = (
                f"⏸ **Human approval required** before executing actions.\n\n"
                f"**Session ID:** `{session_id}`\n\n"
                f"**Proposed actions:**\n{actions_text}\n\n"
                f"Approve via: `POST /hitl/approve/{session_id}`\n"
                f"Reject via:  `POST /hitl/reject/{session_id}`\n"
                f"View via:    `GET  /hitl/pending/{session_id}`"
            )
    except Exception:
        pass  # If state check fails, fall through to normal final_answer handling

    if not final_answer:
        final_answer = "Agent completed but produced no final response."

    yield (
        new_history + [{"role": "assistant", "content": final_answer}],
        "\n".join(log_lines),
    )


with gr.Blocks(title="E-Commerce Ops Agent", theme=gr.themes.Soft()) as demo:
    gr.Markdown("# E-Commerce Ops Agent\nAsk about sales, inventory, marketing, or support issues.")

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

    send_btn.click(
        fn=chat_stream,
        inputs=[msg_box, chatbot, log_box],
        outputs=[chatbot, log_box],
    ).then(lambda: "", outputs=msg_box)

    msg_box.submit(
        fn=chat_stream,
        inputs=[msg_box, chatbot, log_box],
        outputs=[chatbot, log_box],
    ).then(lambda: "", outputs=msg_box)

    clear_btn.click(
        fn=lambda: ([], "Waiting for query..."),
        outputs=[chatbot, log_box],
    )

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860, share=False)
