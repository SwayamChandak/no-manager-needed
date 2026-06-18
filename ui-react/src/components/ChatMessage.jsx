import { cn } from "../lib/utils";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

function ChatMessage({ role, content }) {
  const isUser = role === "user";

  return (
    <div
      className={cn(
        "mb-3 flex",
        isUser ? "justify-end" : "justify-start"
      )}
    >
      <div
        className={cn(
          "max-w-[90%] md:max-w-[80%] rounded-lg px-4 py-2 text-sm",
          isUser
            ? "bg-primary text-primary-foreground"
            : "bg-zinc-800/80 text-foreground border border-zinc-700/50"
        )}
      >
        {isUser ? (
          <span className="whitespace-pre-wrap">{content}</span>
        ) : (
          <div className="prose prose-sm prose-invert max-w-none prose-headings:text-foreground prose-p:text-foreground/90 prose-strong:text-foreground prose-code:text-foreground prose-code:bg-muted prose-code:px-1 prose-code:rounded prose-pre:bg-zinc-900 prose-pre:text-zinc-100 prose-a:text-blue-400 prose-a:no-underline hover:prose-a:underline prose-li:text-foreground/90 prose-th:text-foreground prose-th:border prose-th:border-zinc-700 prose-th:px-3 prose-th:py-2 prose-td:text-foreground/90 prose-td:border prose-td:border-zinc-700 prose-td:px-3 prose-td:py-2 prose-table:w-full">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {content}
            </ReactMarkdown>
          </div>
        )}
      </div>
    </div>
  );
}

export default ChatMessage;
