import { useEffect, useRef } from "react";
import useChatStore from "../store/useChatStore";
import { ScrollArea } from "./ui/scroll-area";

function ActivityLog() {
  const logLines = useChatStore((s) => s.logLines);
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logLines]);

  return (
    <div>
      <p className="text-sm font-medium mb-1">Agent Activity Log</p>
      <ScrollArea className="h-[120px] w-full rounded-md border bg-muted/30 p-3">
        {logLines.length === 0 && (
          <p className="text-xs text-muted-foreground">
            Agent steps will appear here during processing...
          </p>
        )}
        {logLines.map((line, i) => (
          <pre key={i} className="text-xs leading-relaxed whitespace-pre-wrap font-sans">
            {line}
          </pre>
        ))}
        <div ref={bottomRef} />
      </ScrollArea>
    </div>
  );
}

export default ActivityLog;
