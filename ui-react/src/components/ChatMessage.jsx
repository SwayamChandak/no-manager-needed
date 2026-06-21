import { useState } from "react";
import { cn } from "../lib/utils";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { SPECIALIST_COLOURS } from "../lib/constants";

// ── Specialist icon map ───────────────────────────────────────────────────────
const SPECIALIST_ICONS = {
  sales:     "💰",
  inventory: "📦",
  marketing: "📣",
  support:   "🎧",
};

const SPECIALIST_LABELS = {
  sales:     "Sales",
  inventory: "Inventory",
  marketing: "Marketing",
  support:   "Support",
};

// ── Confidence colour ─────────────────────────────────────────────────────────
function confidenceColour(v) {
  if (v >= 0.75) return "text-emerald-400";
  if (v >= 0.45) return "text-amber-400";
  return "text-red-400";
}

// ── Root-cause artifact ───────────────────────────────────────────────────────
function RootCauseCard({ rc, index }) {
  const pct = Math.round((rc.confidence ?? 0) * 100);
  const barColour = pct >= 75 ? "bg-emerald-500" : pct >= 45 ? "bg-amber-500" : "bg-red-500";
  return (
    <div className="rounded-lg border border-zinc-700 bg-zinc-900/60 px-3 py-2.5">
      <div className="flex items-start gap-2">
        <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-zinc-700 text-[10px] font-bold text-zinc-300">
          {index + 1}
        </span>
        <p className="text-sm text-zinc-200 leading-snug">{rc.description}</p>
      </div>
      <div className="mt-2 flex items-center gap-2">
        <div className="h-1.5 flex-1 rounded-full bg-zinc-700">
          <div className={cn("h-1.5 rounded-full transition-all", barColour)} style={{ width: `${pct}%` }} />
        </div>
        <span className={cn("text-[11px] font-semibold tabular-nums", confidenceColour(rc.confidence ?? 0))}>
          {pct}%
        </span>
      </div>
      {rc.supporting_domains?.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {rc.supporting_domains.map((d) => (
            <span key={d} className={cn("inline-block rounded-full px-1.5 py-0.5 text-[10px] font-semibold", SPECIALIST_COLOURS[d] ?? "bg-zinc-700 text-zinc-300")}>
              {SPECIALIST_ICONS[d]} {d}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Recommended action artifact ───────────────────────────────────────────────
function ActionCard({ action }) {
  const actionType = action.action_type ?? "action";
  const impact = action.estimated_impact ?? "";
  const justification = action.justification ?? "";
  const ACTION_COLOURS = {
    restock:         "border-l-blue-500 bg-blue-950/30",
    apply_discount:  "border-l-purple-500 bg-purple-950/30",
    pause_campaign:  "border-l-orange-500 bg-orange-950/30",
    launch_campaign: "border-l-emerald-500 bg-emerald-950/30",
    create_ticket:   "border-l-amber-500 bg-amber-950/30",
  };
  const colour = ACTION_COLOURS[actionType] ?? "border-l-zinc-500 bg-zinc-900/60";
  return (
    <div className={cn("rounded-lg border border-zinc-700 border-l-2 px-3 py-2.5", colour)}>
      <p className="text-xs font-bold uppercase tracking-wide text-zinc-400 mb-1">{actionType.replace(/_/g, " ")}</p>
      {justification && <p className="text-sm text-zinc-200 leading-snug mb-1">{justification}</p>}
      {impact && <p className="text-xs text-zinc-400 italic">{impact}</p>}
    </div>
  );
}

// ── Collapsible artifact section ──────────────────────────────────────────────
function ArtifactSection({ title, count, colour, children, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="mt-3">
      <button
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-xs font-semibold transition-colors",
          "border border-zinc-700 hover:border-zinc-600 hover:bg-zinc-800/60",
          colour,
        )}
      >
        <span>{open ? "▾" : "▸"}</span>
        <span>{title}</span>
        <span className="ml-auto rounded-full bg-zinc-700 px-1.5 py-0.5 text-[10px] font-bold text-zinc-300">{count}</span>
      </button>
      {open && (
        <div className="mt-2 flex flex-col gap-2">{children}</div>
      )}
    </div>
  );
}

// ── Agent trace footer ────────────────────────────────────────────────────────
function AgentTrace({ specialists, confidence }) {
  if (!specialists?.length) return null;
  const hasCF = confidence != null && confidence > 0;
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-zinc-700/60 pt-2.5">
      <span className="text-[11px] font-semibold text-zinc-500 uppercase tracking-wide mr-1">Analysed by</span>
      {specialists.map((s) => (
        <span
          key={s}
          className={cn(
            "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold",
            SPECIALIST_COLOURS[s] ?? "bg-zinc-700 text-zinc-300",
          )}
        >
          {SPECIALIST_ICONS[s]} {SPECIALIST_LABELS[s] ?? s}
        </span>
      ))}
      {hasCF && (
        <span className={cn("ml-auto text-[11px] font-semibold tabular-nums", confidenceColour(confidence))}>
          {Math.round(confidence * 100)}% confidence
        </span>
      )}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────
function ChatMessage({ role, content, meta }) {
  const isUser = role === "user";
  const rootCauses = meta?.rootCauses ?? [];
  const recommendedActions = meta?.recommendedActions ?? [];
  const activeSpecialists = meta?.activeSpecialists ?? [];
  const confidence = meta?.confidence ?? 0;

  const hasArtifacts = rootCauses.length > 0 || recommendedActions.length > 0 || activeSpecialists.length > 0;

  return (
    <div className={cn("mb-3 flex", isUser ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[90%] md:max-w-[80%] rounded-lg px-4 py-2 text-sm",
          isUser
            ? "bg-primary text-primary-foreground"
            : "bg-zinc-800/80 text-foreground border border-zinc-700/50",
        )}
      >
        {isUser ? (
          <span className="whitespace-pre-wrap">{content}</span>
        ) : (
          <>
            <div className="prose prose-sm prose-invert max-w-none prose-headings:text-foreground prose-p:text-foreground/90 prose-strong:text-foreground prose-code:text-foreground prose-code:bg-muted prose-code:px-1 prose-code:rounded prose-pre:bg-zinc-900 prose-pre:text-zinc-100 prose-a:text-blue-400 prose-a:no-underline hover:prose-a:underline prose-li:text-foreground/90 prose-th:text-foreground prose-th:border prose-th:border-zinc-700 prose-th:px-3 prose-th:py-2 prose-td:text-foreground/90 prose-td:border prose-td:border-zinc-700 prose-td:px-3 prose-td:py-2 prose-table:w-full">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
            </div>

            {hasArtifacts && (
              <div className="mt-1">
                {rootCauses.length > 0 && (
                  <ArtifactSection
                    title="Root Causes"
                    count={rootCauses.length}
                    colour="text-red-400"
                    defaultOpen={rootCauses.length <= 3}
                  >
                    {rootCauses.map((rc, i) => (
                      <RootCauseCard key={i} rc={rc} index={i} />
                    ))}
                  </ArtifactSection>
                )}

                {recommendedActions.length > 0 && (
                  <ArtifactSection
                    title="Recommended Actions"
                    count={recommendedActions.length}
                    colour="text-blue-400"
                    defaultOpen={recommendedActions.length <= 4}
                  >
                    {recommendedActions.map((a, i) => (
                      <ActionCard key={i} action={a} />
                    ))}
                  </ArtifactSection>
                )}

                <AgentTrace specialists={activeSpecialists} confidence={confidence} />
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

export default ChatMessage;

