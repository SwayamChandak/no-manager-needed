import { useCallback } from "react";
import useChatStore from "../store/useChatStore";
import { postChatStream } from "../lib/api";
import { readSSEStream } from "../lib/sseStream";
import { NODE_LABELS } from "../lib/constants";

export function useChatStream() {
  const {
    appendUserMessage,
    appendAssistantMessage,
    replaceLastAssistantMessage,
    appendLog,
    replaceLastLog,
    setSessionId,
    setProposedActions,
    setHitlPending,
    setApprovalStatus,
    setIsLoading,
  } = useChatStore();

  const sendMessage = useCallback(async (message) => {
    if (!message.trim()) return;

    const sessionId = crypto.randomUUID();

    appendUserMessage(message);
    appendAssistantMessage("...thinking...");
    setIsLoading(true);

    try {
      const response = await postChatStream(message, sessionId);
      if (!response.ok) {
        replaceLastAssistantMessage(`Error: ${response.status} ${response.statusText}`);
        return;
      }

      for await (const ev of readSSEStream(response)) {
        const etype = ev.type;

        if (etype === "intent_classified") {
          appendLog(`🎯 Intent: ${ev.intent ?? "?"}`);
        } else if (etype === "node_start") {
          const node = ev.node ?? "";
          const label = NODE_LABELS[node] ?? node;
          appendLog(`▶ ${label}…`);
        } else if (etype === "node_end") {
          const node = ev.node ?? "";
          const label = NODE_LABELS[node] ?? node;
          const ms = ev.duration_ms ?? "";
          replaceLastLog(`✓ ${label} (${ms}ms)`);
        } else if (etype === "off_topic") {
          const rejectionMsg = ev.message ?? "I can only help with e-commerce operations topics.";
          const offTopicReply =
            `Out of scope\n\n` +
            `${rejectionMsg}\n\n` +
            `I can help you with:\n` +
            `Sales: revenue drops, order trends, product performance\n` +
            `Inventory: stock levels, stockouts, restock decisions\n` +
            `Marketing: campaign performance, promotions, ad spend\n` +
            `Support: customer complaints, ticket trends, refunds\n\n` +
            `Try asking: "Why did sales drop yesterday?" or "Which products are low on stock?"`;
          replaceLastAssistantMessage(offTopicReply);
          setApprovalStatus("No pending approvals.");
        } else if (etype === "interrupt") {
          const proposedActions = ev.proposed_actions ?? [];
          const sid = ev.session_id ?? sessionId;
          const finalAnswer =
            `Human approval required.\n\n` +
            `${proposedActions.length} action(s) proposed. ` +
            `Review and approve or reject them in the Approvals tab.`;
          setSessionId(sid);
          setProposedActions(proposedActions);
          setHitlPending(true);
          setApprovalStatus(`${proposedActions.length} action(s) are pending your approval. Review the checkboxes below.`);
          replaceLastAssistantMessage(finalAnswer);
        } else if (etype === "result") {
          const finalAnswer = ev.finding ?? ev.result ?? "";
          replaceLastAssistantMessage(finalAnswer);
          setApprovalStatus("No pending approvals.");
        } else if (etype === "error") {
          replaceLastAssistantMessage(`Error: ${ev.message}`);
        }
      }
    } catch (e) {
      replaceLastAssistantMessage(`Error: ${e.message}`);
    } finally {
      setIsLoading(false);
    }
  }, [
    appendUserMessage,
    appendAssistantMessage,
    replaceLastAssistantMessage,
    appendLog,
    replaceLastLog,
    setSessionId,
    setProposedActions,
    setHitlPending,
    setApprovalStatus,
    setIsLoading,
  ]);

  return { sendMessage };
}
