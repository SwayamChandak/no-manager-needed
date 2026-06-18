import { create } from "zustand";

const useChatStore = create((set) => ({
  history: [],
  sessionId: "",
  proposedActions: [],
  hitlPending: false,
  logLines: [],
  approvalStatus: "No pending approvals.",
  isLoading: false,

  appendUserMessage: (content) =>
    set((state) => ({
      history: [...state.history, { role: "user", content }],
    })),

  appendAssistantMessage: (content) =>
    set((state) => ({
      history: [...state.history, { role: "assistant", content }],
    })),

  replaceLastAssistantMessage: (content) =>
    set((state) => {
      const history = [...state.history];
      for (let i = history.length - 1; i >= 0; i--) {
        if (history[i].role === "assistant") {
          history[i] = { ...history[i], content };
          break;
        }
      }
      return { history };
    }),

  clearHistory: () =>
    set({
      history: [],
      logLines: [],
      sessionId: "",
      proposedActions: [],
      hitlPending: false,
      approvalStatus: "No pending approvals.",
    }),

  appendLog: (line) =>
    set((state) => ({
      logLines: [...state.logLines, line],
    })),

  replaceLastLog: (line) =>
    set((state) => {
      const logLines = [...state.logLines];
      if (logLines.length > 0) {
        logLines[logLines.length - 1] = line;
      }
      return { logLines };
    }),

  setSessionId: (id) => set({ sessionId: id }),
  setProposedActions: (actions) => set({ proposedActions: actions }),
  setHitlPending: (bool) => set({ hitlPending: bool }),
  setApprovalStatus: (text) => set({ approvalStatus: text }),
  setIsLoading: (bool) => set({ isLoading: bool }),

  resetHitl: () =>
    set({
      sessionId: "",
      proposedActions: [],
      hitlPending: false,
      approvalStatus: "No pending approvals.",
    }),
}));

export default useChatStore;
