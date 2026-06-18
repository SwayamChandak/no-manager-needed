import { useChatStream } from "../hooks/useChatStream";
import useChatStore from "../store/useChatStore";
import ChatHistory from "./ChatHistory";
import MessageInput from "./MessageInput";
import ActivityLog from "./ActivityLog";

function ChatTab() {
  const isLoading = useChatStore((s) => s.isLoading);
  const clearHistory = useChatStore((s) => s.clearHistory);
  const { sendMessage } = useChatStream();

  return (
    <div className="flex flex-col gap-4">
      <ChatHistory />
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
