import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import useChatStore from "../store/useChatStore";
import { ScrollArea } from "./ui/scroll-area";
import { NODE_LABELS } from "../lib/constants";
import { Button } from "./ui/button";

const NODE_COLOURS = {
  orchestrator_node:     "bg-emerald-600",
  sales_node:            "bg-emerald-500",
  inventory_node:        "bg-blue-500",
  marketing_node:        "bg-purple-500",
  support_node:          "bg-orange-500",
  aggregator_node:       "bg-cyan-600",
  reflection_node:       "bg-amber-600",
  hitl_node:             "bg-red-600",
  action_executor_node:  "bg-pink-600",
  memory_writer_node:    "bg-indigo-600",
  output_formatter_node: "bg-zinc-500",
  recall_node:           "bg-violet-500",
};

function getNodeBadge(node) {
  const label = NODE_LABELS[node] ?? node;
  const colour = NODE_COLOURS[node] ?? "bg-zinc-600";
  return { label, colour };
}

function tryFormatJSON(raw) {
  try {
    const parsed = JSON.parse(raw);
    return JSON.stringify(parsed, null, 2);
  } catch {
    return null;
  }
}

function StreamSidebar() {
  const streamTokens = useChatStore((s) => s.streamTokens);
  const isStreaming = useChatStore((s) => s.isStreaming);
  const clearStream = useChatStore((s) => s.clearStream);
  const [collapsed, setCollapsed] = useState(false);
  const [expandedGroups, setExpandedGroups] = useState({});
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [streamTokens]);

  if (streamTokens.length === 0 && !isStreaming) return null;

  // Group tokens by node, concatenating content per node
  const groups = [];
  for (const t of streamTokens) {
    if (t.node === "output_formatter_node") continue;
    const prev = groups[groups.length - 1];
    if (prev && prev.node === t.node) {
      prev.content += t.content;
    } else {
      groups.push({ node: t.node, content: t.content });
    }
  }

  const toggleGroup = (idx) => {
    setExpandedGroups((prev) => ({ ...prev, [idx]: !prev[idx] }));
  };

  const rows = [];
  for (let i = 0; i < groups.length; i++) {
    const g = groups[i];
    const { label, colour } = getNodeBadge(g.node);
    const isLast = i === groups.length - 1;
    const formatted = tryFormatJSON(g.content);
    const isExpanded = expandedGroups[i] ?? !formatted; // auto-collapse JSON

    rows.push(
      <div key={`hdr-${i}`} className="mt-1.5 mb-0.5 flex items-center gap-2">
        <span className={`inline-block rounded px-1 py-0.5 text-[10px] font-bold text-white ${colour}`}>
          {label}
        </span>
      </div>
    );

    if (formatted) {
      const preview = g.content.slice(0, 80) + (g.content.length > 80 ? "…" : "");
      rows.push(
        <div key={`json-${i}`} className="mb-1">
          <button
            onClick={() => toggleGroup(i)}
            className="w-full text-left text-[10px] text-zinc-400 hover:text-zinc-200 font-mono truncate"
          >
            {isExpanded ? "▾" : "▸"} {preview}
          </button>
          {isExpanded && (
            <pre className="mt-1 rounded bg-zinc-950 p-2 text-[10px] text-zinc-300 overflow-x-auto whitespace-pre-wrap">
              {formatted}
            </pre>
          )}
        </div>
      );
    } else {
      rows.push(
        <div key={`txt-${i}`} className="mb-1">
          <div className="prose prose-xs prose-invert max-w-none prose-headings:text-foreground prose-p:text-foreground/80 prose-p:my-0.5 prose-p:leading-relaxed prose-strong:text-foreground prose-code:text-foreground prose-code:bg-muted prose-code:px-1 prose-code:rounded prose-pre:bg-zinc-950 prose-pre:text-zinc-300 prose-pre:text-[10px] prose-a:text-blue-400 prose-a:no-underline hover:prose-a:underline prose-li:text-foreground/80 prose-li:my-0">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{g.content}</ReactMarkdown>
          </div>
          {isLast && isStreaming && (
            <span className="inline-block w-1.5 h-3.5 bg-primary/60 animate-pulse ml-0.5" />
          )}
        </div>
      );
    }
  }

  return (
    <div className="w-[560px] h-[calc(100vh-120px)] shrink-0 rounded-md border border-zinc-700/60 bg-zinc-900/40 flex flex-col">
      <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-700/40">
        <div className="flex items-center gap-2">
          <p className="text-xs font-semibold text-zinc-300">Live Stream</p>
          <span className={`inline-block w-1.5 h-1.5 rounded-full ${isStreaming ? "bg-emerald-400 animate-pulse" : "bg-zinc-600"}`} />
          <span className="text-[10px] text-zinc-500">{streamTokens.length} tok</span>
        </div>
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="sm" className="h-5 px-1.5 text-[10px]" onClick={() => setCollapsed((c) => !c)}>
            {collapsed ? "▸" : "▾"}
          </Button>
          <Button variant="ghost" size="sm" className="h-5 px-1.5 text-[10px] text-zinc-500 hover:text-zinc-300" onClick={clearStream}>
            ✕
          </Button>
        </div>
      </div>
      {!collapsed && (
        <ScrollArea className="flex-1 p-3 font-mono text-xs leading-relaxed">
          {rows}
          <div ref={bottomRef} />
        </ScrollArea>
      )}
    </div>
  );
}

export default StreamSidebar;
