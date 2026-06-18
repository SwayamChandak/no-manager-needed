const BASE_URL = "";

export async function postChatStream(message, sessionId) {
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
