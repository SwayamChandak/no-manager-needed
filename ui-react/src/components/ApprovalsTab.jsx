import { useState, useEffect } from "react";
import useChatStore from "../store/useChatStore";
import { useHitl } from "../hooks/useHitl";
import { buildActionLabels } from "../lib/constants";
import ActionCheckboxGroup from "./ActionCheckboxGroup";
import RejectionReasonInput from "./RejectionReasonInput";
import ApprovalButtons from "./ApprovalButtons";

function ApprovalsTab() {
  const hitlPending = useChatStore((s) => s.hitlPending);
  const approvalStatus = useChatStore((s) => s.approvalStatus);
  const proposedActions = useChatStore((s) => s.proposedActions);
  const isLoading = useChatStore((s) => s.isLoading);
  const { handleApprove, handleReject } = useHitl();

  const labeledActions = buildActionLabels(proposedActions);
  const defaultSelected = labeledActions.map((item) => item.label);
  const [selected, setSelected] = useState(defaultSelected);
  const [rejectionReason, setRejectionReason] = useState("");

  useEffect(() => {
    setSelected(labeledActions.map((item) => item.label));
  }, [proposedActions]); // eslint-disable-line react-hooks/exhaustive-deps

  const onConfirm = () => {
    handleApprove(selected);
  };

  const onReject = () => {
    handleReject(rejectionReason);
  };

  if (!hitlPending) {
    return (
      <div className="rounded-md border p-6">
        <p className="text-muted-foreground">{approvalStatus}</p>
      </div>
    );
  }

  return (
    <div className="rounded-md border p-6 space-y-4">
      <p className="font-medium">{approvalStatus}</p>
      <p className="text-sm text-muted-foreground">
        The agent has proposed the following actions. Uncheck any you want to
        skip, then click Confirm Selections. Or click Reject All to cancel
        without making any changes.
      </p>
      <ActionCheckboxGroup
        items={labeledActions}
        selected={selected}
        onChange={setSelected}
      />
      <RejectionReasonInput
        value={rejectionReason}
        onChange={setRejectionReason}
      />
      <ApprovalButtons
        onConfirm={onConfirm}
        onReject={onReject}
        disabled={isLoading}
      />
    </div>
  );
}

export default ApprovalsTab;
