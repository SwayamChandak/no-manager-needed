// Specialist badge colours (Tailwind classes)
export const SPECIALIST_COLOURS = {
  sales:     "bg-emerald-100 text-emerald-700",
  inventory: "bg-blue-100 text-blue-700",
  marketing: "bg-purple-100 text-purple-700",
  support:   "bg-orange-100 text-orange-700",
};

// Starter prompts shown before the first message.
// specialists[] drives the coloured badge pills on each card.
export const STARTER_PROMPTS = [
  // ── single-specialist ───────────────────────────────────────────────
  {
    label: "Top products last 30 days",
    prompt: "What were the top-selling products by revenue over the last 30 days?",
    specialists: ["sales"],
  },
  {
    label: "Low stock alerts",
    prompt: "Which products are running low and need restocking right now?",
    specialists: ["inventory"],
  },
  {
    label: "Campaign performance",
    prompt: "How are my active marketing campaigns performing overall?",
    specialists: ["marketing"],
  },
  {
    label: "Recent complaints",
    prompt: "What are the most common customer complaints and support issues recently?",
    specialists: ["support"],
  },
  // ── two-specialist cross-domain ─────────────────────────────────────
  {
    label: "Fast sellers vs. low stock",
    prompt:
      "Which top-selling products are at risk of stocking out soon? Cross-reference revenue leaders with current inventory levels.",
    specialists: ["sales", "inventory"],
  },
  {
    label: "Campaign revenue impact",
    prompt:
      "Are my active campaigns driving measurable revenue uplift compared to baseline sales trends?",
    specialists: ["sales", "marketing"],
  },
  {
    label: "Campaigns on out-of-stock items",
    prompt:
      "Are there any products that are currently out of stock but still have active marketing campaigns running on them?",
    specialists: ["inventory", "marketing"],
  },
  {
    label: "Refunds & order volume",
    prompt:
      "Have elevated refund rates or customer complaints been correlated with a recent drop in order volume?",
    specialists: ["support", "sales"],
  },
];

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
