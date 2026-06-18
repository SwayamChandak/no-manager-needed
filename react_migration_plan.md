# React Migration Plan: `ui/chatbot.py` → Create React App

## Overview

Replace the Gradio UI (`ui/chatbot.py`, mounted at `/ui` by FastAPI) with a **Create React App** (JavaScript) application using **Tailwind CSS + shadcn/ui** for components and **Zustand** for state management. The React build output will be served by FastAPI at the same `/ui` path, replacing the Gradio mount. No backend endpoint changes are required.

---

## Architecture Reference

### Backend endpoints consumed by the UI

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/chat/stream` | SSE stream. Body: `{message, session_id, intent}` |
| `POST` | `/hitl/approve/{session_id}` | Approve HITL actions. Body: `{modified_actions}` |
| `POST` | `/hitl/reject/{session_id}` | Reject HITL actions. Body: `{reason}` |
| `GET` | `/hitl/pending` | List pending session IDs |

### SSE event types (from `/chat/stream`)

| `type` field | Payload fields | Action in UI |
|---|---|---|
| `intent_classified` | `intent` | Append to activity log |
| `node_start` | `node` | Append "▶ Node…" to log |
| `node_end` | `node`, `duration_ms` | Replace last log line with "✓ Node (Xms)" |
| `off_topic` | `message` | Show rejection message in chat, clear log |
| `interrupt` | `proposed_actions`, `session_id` | Show HITL panel, populate checkboxes |
| `result` | `finding`, `session_id`, … | Show final answer in chat |
| `error` | `message` | Show error in chat |

### State equivalents (Gradio → Zustand)

| Gradio State | Zustand field | Type |
|---|---|---|
| `session_id_state` | `sessionId` | `string` |
| `proposed_actions_state` | `proposedActions` | `array` |
| `hitl_pending_state` | `hitlPending` | `boolean` |
| implicit chatbot history | `history` | `array<{role, content}>` |
| implicit log lines | `logLines` | `array<string>` |
| approval status markdown | `approvalStatus` | `string` |

### Node label map (port from `_NODE_LABELS` in `chatbot.py`)

Preserved verbatim as a JS constant. Maps internal node names (e.g., `orchestrator_node`) to display labels (e.g., `🧠 Orchestrator`).

---

## Important Technical Note: POST-based SSE

The `/chat/stream` endpoint is a **POST** request that streams SSE. The browser-native `EventSource` API only supports `GET` — it cannot be used here. The React app must use `fetch()` with a `ReadableStream` reader and manually parse `data: {...}\n\n` lines. This must be implemented as a custom utility.

---

## Phase 1 — Scaffold the React App

### 1.1 Create the CRA project

Create the React app inside a new `ui-react/` directory at the project root (sibling to `ui/`):

```
npx create-react-app ui-react
```

The resulting `ui-react/` directory becomes the new frontend source. The old `ui/chatbot.py` and `ui/` directory remain untouched until Phase 10 confirms the React app works end-to-end.

### 1.2 Install dependencies

Inside `ui-react/`:

```
npm install zustand
npm install -D tailwindcss postcss autoprefixer
npx tailwindcss init -p
```

For shadcn/ui (requires manual setup since CRA is not Next.js):

```
npm install @radix-ui/react-checkbox @radix-ui/react-tabs @radix-ui/react-scroll-area
npm install class-variance-authority clsx tailwind-merge lucide-react
```

Install shadcn/ui components manually (copy component source files) or use the CLI with the `--cra` flag if the version supports it. Each needed component (`Button`, `Checkbox`, `Tabs`, `Textarea`, `ScrollArea`, `Badge`) should be copied into `src/components/ui/`.

### 1.3 Configure Tailwind

In `tailwind.config.js`, set `content` to cover all source files:

```js
content: ["./src/**/*.{js,jsx}"]
```

Add `@tailwind` directives to `src/index.css`.

### 1.4 Set `homepage` in `package.json`

Since FastAPI serves the app at `/ui`, CRA must build with that base path:

```json
"homepage": "/ui"
```

This causes all asset references (`/static/js/…`) in the built `index.html` to be prefixed with `/ui`, matching the mount point.

### 1.5 Configure proxy for local development

In `ui-react/package.json`, add:

```json
"proxy": "http://localhost:8002"
```

This proxies all `/chat/…` and `/hitl/…` fetch calls to the FastAPI server during `npm start`, so no CORS issues or hardcoded ports are needed in development.

### 1.6 Final project structure inside `ui-react/src/`

```
src/
  index.js               ← CRA entry point, renders <App />
  App.jsx                ← Root component, renders Tabs layout
  index.css              ← Tailwind directives
  store/
    useChatStore.js      ← Zustand store
  lib/
    api.js               ← Fetch wrappers for backend endpoints
    sseStream.js         ← POST-SSE reader utility
    constants.js         ← NODE_LABELS map, action label builder
  hooks/
    useChatStream.js     ← Hook: send message, consume SSE, update store
    useHitl.js           ← Hook: approve / reject actions
  components/
    ChatTab.jsx          ← Chat tab root
    ChatHistory.jsx      ← Scrollable chat message list
    ChatMessage.jsx      ← Single message bubble (user vs assistant)
    ActivityLog.jsx      ← Live log panel
    MessageInput.jsx     ← Textarea + Send + Clear buttons
    ApprovalsTab.jsx     ← Approvals tab root
    ActionCheckboxGroup.jsx  ← Per-action checkboxes
    RejectionReasonInput.jsx ← Rejection reason textarea
    ApprovalButtons.jsx  ← Confirm / Reject buttons
    ui/                  ← shadcn/ui copied component files
      button.jsx
      checkbox.jsx
      tabs.jsx
      textarea.jsx
      scroll-area.jsx
      badge.jsx
```

---

## Phase 2 — Zustand Store (`src/store/useChatStore.js`)

Create a single Zustand store that holds all shared state and the setters for it. This replaces Gradio's `gr.State` objects.

### State fields

| Field | Initial value | Description |
|---|---|---|
| `history` | `[]` | Chat messages: `{role: "user"\|"assistant", content: string}` |
| `sessionId` | `""` | Current session UUID (set on first SSE response per query) |
| `proposedActions` | `[]` | Raw action objects from the `interrupt` SSE event |
| `hitlPending` | `false` | Whether the HITL panel should be shown |
| `logLines` | `[]` | Activity log lines for the current request |
| `approvalStatus` | `"No pending approvals."` | Text shown at top of Approvals tab |
| `isLoading` | `false` | Disables the Send button while a stream is in progress |

### Actions (store methods)

- `appendUserMessage(content)` — push `{role:"user", content}` to `history`
- `appendAssistantMessage(content)` — push `{role:"assistant", content}` to `history`
- `replaceLastAssistantMessage(content)` — replace the last assistant entry (used to swap "...thinking..." for the real answer)
- `clearHistory()` — reset `history`, `logLines`, `sessionId`, `proposedActions`, `hitlPending` to initial values
- `appendLog(line)` — push a line to `logLines`
- `replaceLastLog(line)` — replace last `logLines` entry (used when `node_end` follows a `node_start`)
- `setSessionId(id)`
- `setProposedActions(actions)`
- `setHitlPending(bool)`
- `setApprovalStatus(text)`
- `setIsLoading(bool)`
- `resetHitl()` — clears `sessionId`, `proposedActions`, `hitlPending`, `approvalStatus`

---

## Phase 3 — API Service Layer (`src/lib/api.js`)

Centralize all HTTP calls. No fetch logic should appear directly in components.

```js
// Base URL: in production (served by FastAPI) this is relative ("").
// In development the proxy in package.json forwards to http://localhost:8002.
const BASE_URL = "";

export async function postChatStream(message, sessionId) {
  // Returns a raw fetch Response so the caller can read the body as a stream.
  return fetch(`${BASE_URL}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, session_id: sessionId, intent: "auto" }),
  });
}

export async function postApprove(sessionId, modifiedActions) {
  const resp = await fetch(`${BASE_URL}/hitl/approve/${sessionId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ modified_actions: modifiedActions }),
  });
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

export async function postReject(sessionId, reason) {
  const resp = await fetch(`${BASE_URL}/hitl/reject/${sessionId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason: reason || null }),
  });
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}
```

---

## Phase 4 — POST-SSE Utility (`src/lib/sseStream.js`)

Since `EventSource` does not support POST, implement a manual line-by-line reader over a `fetch` `ReadableStream`.

```js
/**
 * Async generator that yields parsed event objects from a POST SSE stream.
 * @param {Response} response - The raw fetch Response from postChatStream()
 */
export async function* readSSEStream(response) {
  const decoder = new TextDecoder();
  const reader = response.body.getReader();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // Split on double-newline (SSE event boundary)
    const parts = buffer.split("\n\n");
    buffer = parts.pop(); // keep incomplete tail

    for (const part of parts) {
      for (const line of part.split("\n")) {
        if (line.startsWith("data: ")) {
          try {
            yield JSON.parse(line.slice(6));
          } catch {
            // malformed line — skip
          }
        }
      }
    }
  }
}
```

---

## Phase 5 — Constants (`src/lib/constants.js`)

Port `_NODE_LABELS` and `_build_action_labels` from `chatbot.py` to JavaScript.

```js
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

/**
 * Converts raw proposed_actions array to label strings.
 * Mirrors _build_action_labels() from chatbot.py.
 * Returns [{ label, action }] where label is the display string.
 */
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
```

---

## Phase 6 — Chat Stream Hook (`src/hooks/useChatStream.js`)

This hook encapsulates the full SSE lifecycle. It is called when the user submits a message. It updates the Zustand store as each SSE event arrives — this is the direct equivalent of the `chat_fn` generator in `chatbot.py`.

### Responsibilities

1. Generate a new `session_id` (UUID) for each query.
2. Append the user message to `history`.
3. Add a placeholder `"...thinking..."` assistant message.
4. Call `postChatStream()` from `api.js` and iterate over events via `readSSEStream()`.
5. For each event type, call the appropriate Zustand store action:

| SSE `type` | Zustand action(s) |
|---|---|
| `intent_classified` | `appendLog("🎯 Intent: " + intent)` |
| `node_start` | `appendLog("▶ " + NODE_LABELS[node] + "…")` |
| `node_end` | `replaceLastLog("✓ " + NODE_LABELS[node] + " (" + ms + "ms)")` |
| `off_topic` | `replaceLastAssistantMessage(rejection_text)`, `setApprovalStatus("No pending approvals.")` |
| `interrupt` | `setSessionId(sid)`, `setProposedActions(actions)`, `setHitlPending(true)`, `setApprovalStatus("N action(s) are pending your approval.")`, `replaceLastAssistantMessage(...)` |
| `result` | `replaceLastAssistantMessage(finding)`, `setApprovalStatus("No pending approvals.")` |
| `error` | `replaceLastAssistantMessage("Error: " + message)` |

6. Set `isLoading(false)` in a `finally` block.

The `off_topic` message construction must mirror the Gradio code exactly — it shows a multi-line rejection with the four topic categories listed.

---

## Phase 7 — HITL Hook (`src/hooks/useHitl.js`)

Encapsulates the approve and reject flows. Direct equivalent of `handle_approve` and `handle_reject` in `chatbot.py`.

### `handleApprove(selectedLabels, labelToActionMap)`

1. Build `filteredActions` — actions whose labels are in `selectedLabels`.
2. Append `"✅ Approved N action(s)."` as a user message.
3. Call `postApprove(sessionId, filteredActions)`.
4. On success: append the returned `message` as an assistant message, call `resetHitl()`, clear log.
5. On error: append error message.

### `handleReject(rejectionReason)`

1. Append `"❌ Rejected all proposed actions. Reason: ..."` as user message.
2. Call `postReject(sessionId, rejectionReason)`.
3. On success: append returned `message` as assistant message, call `resetHitl()`, clear log.
4. On error: append error message.

---

## Phase 8 — Components

### `App.jsx`

Root component. Renders the two-tab layout using `shadcn/ui Tabs`.

```
<Tabs defaultValue="chat">
  <TabsList>
    <TabsTrigger value="chat">💬 Chat</TabsTrigger>
    <TabsTrigger value="approvals">⏸ Approvals</TabsTrigger>
  </TabsList>
  <TabsContent value="chat"><ChatTab /></TabsContent>
  <TabsContent value="approvals"><ApprovalsTab /></TabsContent>
</Tabs>
```

### `ChatTab.jsx`

Reads `history`, `logLines`, `isLoading` from Zustand. Uses `useChatStream` hook.

- Renders `<ChatHistory />` at the top (scrollable, 500px height equivalent).
- Renders `<MessageInput />` at the bottom with Send + Clear.
- Renders `<ActivityLog />` below the input.
- Calls `useChatStream().sendMessage(message)` on submit.
- `clearHistory()` from the store on Clear.
- Auto-scrolls `ChatHistory` to bottom after each new message (use a `useEffect` on `history`).

### `ChatHistory.jsx`

Receives `history` from props or reads from store. Renders each message as `<ChatMessage />`. Wrapped in a `ScrollArea` with a fixed height.

### `ChatMessage.jsx`

Props: `role` (`"user"` | `"assistant"`), `content` (string).

- User messages: right-aligned, distinct background.
- Assistant messages: left-aligned, lighter background.
- Content is rendered as plain text (`white-space: pre-wrap` to preserve line breaks from the backend).

### `ActivityLog.jsx`

Reads `logLines` from store. Renders as a `<pre>` or line-separated `<div>` inside a `ScrollArea`. Mirrors the Gradio `gr.Textbox` activity log. Auto-scrolls to the bottom.

### `MessageInput.jsx`

Local state for the current input value. `onSubmit` calls `sendMessage`, then clears the local value. "Send" button is disabled when `isLoading` is true or when the input is empty. Submits on Enter key (matches Gradio `msg_box.submit` behavior).

### `ApprovalsTab.jsx`

Reads `approvalStatus`, `proposedActions`, `hitlPending`, `sessionId` from store. Uses `useHitl` hook.

- Renders `<p>{approvalStatus}</p>` at the top.
- Renders `<ActionCheckboxGroup />` with the built action labels.
- Renders `<RejectionReasonInput />`.
- Renders `<ApprovalButtons />`.

### `ActionCheckboxGroup.jsx`

Props: `items` (array of `{label, action}`), `selected` (array of label strings), `onChange` (callback).

- Renders one `<Checkbox>` per action.
- All items are pre-checked by default (mirrors Gradio's `default_value = choices`).
- Unchecking excludes that action from the approved set.
- The `selected` state is local to `ApprovalsTab` (use `useState`, initialized from `proposedActions` on mount/change).

### `RejectionReasonInput.jsx`

A `<Textarea>` from shadcn/ui. Controlled via local state in `ApprovalsTab`. Passed down as prop.

### `ApprovalButtons.jsx`

Props: `onConfirm`, `onReject`, `disabled`.

- "✅ Confirm Selections" → calls `onConfirm`.
- "❌ Reject All" → calls `onReject`.
- Both are disabled when `isLoading` is true.

---

## Phase 9 — FastAPI Integration (Backend Changes)

This is the only phase that modifies existing backend files.

### 9.1 `api/app.py` — Replace Gradio mount

**Remove** these lines:

```python
import gradio as gr
from ui.chatbot import demo as gradio_demo  # noqa: E402
app = gr.mount_gradio_app(app, gradio_demo, path="/ui")
```

**Add** static file serving:

```python
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

# Serve the React build at /ui
_react_build = os.path.join(os.path.dirname(__file__), "..", "ui-react", "build")
if os.path.isdir(_react_build):
    app.mount("/ui", StaticFiles(directory=_react_build, html=True), name="ui")
```

The `StaticFiles(html=True)` flag causes FastAPI to serve `index.html` automatically for any path under `/ui` that does not match a static asset — this is the SPA fallback behavior needed so that a browser refresh on `/ui` still works.

### 9.2 `requirements.txt` — Remove Gradio

Remove the `gradio` line from `requirements.txt` once the React app is confirmed working. This is an optional cleanup step, not a blocking change.

### 9.3 No changes to any other backend file

`/chat/stream`, `/hitl/approve/{id}`, `/hitl/reject/{id}` are unchanged. The HITL store, graph, and all agent logic remain untouched.

---

## Phase 10 — Build & Deployment

### Development workflow

```bash
# Terminal 1: run FastAPI backend
python -m api

# Terminal 2: run React dev server (proxies /chat and /hitl to FastAPI)
cd ui-react
npm start
```

During development, access the UI at `http://localhost:3000` (CRA dev server), not at `/ui` on the FastAPI server. The proxy in `package.json` routes `/chat/stream` → `http://localhost:8002/chat/stream`.

### Production build

```bash
cd ui-react
npm run build
```

The `build/` output is placed at `ui-react/build/`. FastAPI's `StaticFiles` mount (added in Phase 9) serves it at `http://localhost:8002/ui`. The `"homepage": "/ui"` in `package.json` ensures all asset URLs in `index.html` are correctly prefixed.

---

## Phase 11 — Verification Checklist

After completing all phases, test the following scenarios against the running FastAPI server:

- [ ] The page loads at `http://localhost:8002/ui` without errors.
- [ ] A chat message is sent and the activity log shows intent + node events in real time.
- [ ] A `diagnose` query returns a result that appears in the chat history.
- [ ] A `recall` query shows node_start / node_end events in the log.
- [ ] An off-topic query shows the rejection message with the four topic categories.
- [ ] A `fix` query triggers the HITL interrupt: the Approvals tab status updates and checkboxes are populated with all actions pre-checked.
- [ ] Unchecking one action and clicking "Confirm Selections" sends only the remaining actions to `/hitl/approve`.
- [ ] Clicking "Reject All" without a reason → verify backend accepts it (reason is nullable).
- [ ] Clicking "Reject All" with a reason → reason appears in the user message and is sent to `/hitl/reject`.
- [ ] After approve or reject, the Approvals tab shows "No pending approvals." and checkboxes are cleared.
- [ ] The Clear button resets the chat, log, and all state.
- [ ] Browser page refresh at `/ui` reloads correctly (SPA fallback works).
- [ ] The Send button is disabled while a stream is in progress.

---

## File Change Summary

| File | Action |
|---|---|
| `ui-react/` (entire directory) | **Create** — new CRA project |
| `ui-react/package.json` | Set `"homepage": "/ui"`, `"proxy": "http://localhost:8002"` |
| `ui-react/src/` | Implement all components, hooks, store, lib as above |
| `api/app.py` | Replace Gradio mount with `StaticFiles` serving `ui-react/build/` |
| `requirements.txt` | Remove `gradio` (after verification) |
| `ui/chatbot.py` | **Delete** (after verification) |
| `ui/__init__.py` | **Delete** (after verification) |
