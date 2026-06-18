import { Button } from "./ui/button";

function ApprovalButtons({ onConfirm, onReject, disabled }) {
  return (
    <div className="flex gap-2">
      <Button onClick={onConfirm} disabled={disabled}>
        ✅ Confirm Selections
      </Button>
      <Button variant="destructive" onClick={onReject} disabled={disabled}>
        ❌ Reject All
      </Button>
    </div>
  );
}

export default ApprovalButtons;
