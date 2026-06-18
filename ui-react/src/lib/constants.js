export const NODE_LABELS = {
  orchestrator_node:     "🧠 Orchestrator",
  sales_node:            "💰 Sales Specialist",
  inventory_node:        "📦 Inventory Specialist",
  marketing_node:        "📣 Marketing Specialist",
  support_node:          "🎧 Support Specialist",
  aggregator_node:       "🔗 Aggregator",
  reflection_node:       "🔍 Reflection",
  hitl_node:             "⏸ HITL Checkpoint",
  action_executor_node:  "⚡ Action Executor",
  memory_writer_node:    "💾 Memory Writer",
  output_formatter_node: "📝 Output Formatter",
  recall_node:           "🗂 Recall",
};

export function buildActionLabels(proposedActions) {
  return proposedActions.map((action, i) => {
    const actionType = action.action_type ?? `action_${i}`;
    const impact = action.estimated_impact ?? "";
    const justification = (action.justification ?? "").slice(0, 80);
    return {
      label: `${actionType} | Impact: ${impact} | ${justification}`,
      action,
    };
  });
}
