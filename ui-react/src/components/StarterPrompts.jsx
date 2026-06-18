import { STARTER_PROMPTS, SPECIALIST_COLOURS } from "../lib/constants";

/**
 * Starter-prompt chips shown in the chat panel before the first message.
 * Clicking a chip immediately fires `onSelect(prompt)`.
 */
function StarterPrompts({ onSelect, disabled }) {
  return (
    <div className="flex flex-col gap-3 py-2">
      <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
        Suggested prompts
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {STARTER_PROMPTS.map((item) => (
          <button
            key={item.label}
            disabled={disabled}
            onClick={() => onSelect(item.prompt)}
            className="text-left rounded-lg border border-border bg-card px-3 py-2.5 hover:bg-accent hover:border-accent-foreground/20 transition-colors disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <span className="block text-sm font-medium text-foreground leading-snug mb-1.5">
              {item.label}
            </span>
            <div className="flex flex-wrap gap-1">
              {item.specialists.map((s) => (
                <span
                  key={s}
                  className={`inline-block text-[10px] font-semibold px-1.5 py-0.5 rounded-full ${SPECIALIST_COLOURS[s]}`}
                >
                  {s}
                </span>
              ))}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

export default StarterPrompts;
