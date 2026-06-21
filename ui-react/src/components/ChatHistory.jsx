import { useEffect, useRef } from "react";
import useChatStore from "../store/useChatStore";
import ChatMessage from "./ChatMessage";
import { ScrollArea } from "./ui/scroll-area";

function ChatHistory() {
  const history = useChatStore((s) => s.history);
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [history]);

  return (
    <ScrollArea className="h-[500px] w-full rounded-md border p-4">
      {history.length === 0 && (
        <p className="text-muted-foreground text-sm">Start a conversation above.</p>
      )}
      {history.map((msg, i) => (
        <ChatMessage key={i} role={msg.role} content={msg.content} meta={msg.meta} />
      ))}
      <div ref={bottomRef} />
    </ScrollArea>
  );
}

export default ChatHistory;
