import { useCallback } from "react";
import useChatStore from "../store/useChatStore";
import { postApprove, postReject } from "../lib/api";
import { buildActionLabels } from "../lib/constants";

export function useHitl() {
  const sessionId = useChatStore((s) => s.sessionId);
  const proposedActions = useChatStore((s) => s.proposedActions);
  const {
    appendUserMessage,
    appendAssistantMessage,
    resetHitl,
  } = useChatStore();

  const handleApprove = useCallback(async (selectedLabels) => {
    if (!sessionId) return;

    const labeledActions = buildActionLabels(proposedActions);
    const labelToAction = {};
    for (const item of labeledActions) {
      labelToAction[item.label] = item.action;
    }

    const filteredActions = selectedLabels
      .map((lbl) => labelToAction[lbl])
      .filter(Boolean);

    appendUserMessage(`✅ Approved ${filteredActions.length} action(s).`);

    try {
      const data = await postApprove(sessionId, filteredActions);
      const finalText = data.message ?? "Actions approved and executed successfully.";
      appendAssistantMessage(finalText);
      resetHitl();
    } catch (e) {
      appendAssistantMessage(`Error approving: ${e.message}`);
    }
  }, [sessionId, proposedActions, appendUserMessage, appendAssistantMessage, resetHitl]);

  const handleReject = useCallback(async (rejectionReason) => {
    if (!sessionId) return;

    const reasonDisplay = (rejectionReason && rejectionReason.trim())
      ? rejectionReason.trim()
      : "No reason provided.";

    appendUserMessage(`❌ Rejected all proposed actions. Reason: ${reasonDisplay}`);

    try {
      const data = await postReject(sessionId, rejectionReason?.trim() || null);
      const finalText = data.message ?? "All proposed actions were rejected. No changes were made.";
      appendAssistantMessage(finalText);
      resetHitl();
    } catch (e) {
      appendAssistantMessage(`Error rejecting: ${e.message}`);
    }
  }, [sessionId, appendUserMessage, appendAssistantMessage, resetHitl]);

  return { handleApprove, handleReject };
}
