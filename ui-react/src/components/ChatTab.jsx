import { useChatStream } from "../hooks/useChatStream";
import useChatStore from "../store/useChatStore";
import ChatHistory from "./ChatHistory";
import MessageInput from "./MessageInput";
import ActivityLog from "./ActivityLog";
import StarterPrompts from "./StarterPrompts";

function ChatTab() {
  const isLoading = useChatStore((s) => s.isLoading);
  const clearHistory = useChatStore((s) => s.clearHistory);
  const history = useChatStore((s) => s.history);
  const { sendMessage } = useChatStream();

  return (
    <div className="flex flex-col gap-4">
      <ChatHistory />
      {history.length === 0 && (
        <StarterPrompts onSelect={sendMessage} disabled={isLoading} />
      )}
      <MessageInput
        onSend={sendMessage}
        onClear={clearHistory}
        isLoading={isLoading}
      />
      <ActivityLog />
    </div>
  );
}

export default ChatTab;
