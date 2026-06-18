function RejectionReasonInput({ value, onChange }) {
  return (
    <div>
      <p className="text-sm font-medium mb-1">
        Rejection Reason (required when rejecting)
      </p>
      <textarea
        className="w-full min-h-[60px] rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 resize-none"
        placeholder="Explain why you are rejecting these actions..."
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={2}
      />
    </div>
  );
}

export default RejectionReasonInput;
