"""
api/hitl_store.py — Centralized in-memory store for pending HITL sessions.

Both api/hitl_api.py and mcp_server/mcp_tools.py import the singleton
`hitl_store` from this module, eliminating the previously disconnected
_pending_sessions / _hitl_pending dual-store bug.

For production, replace the dict with a Redis or Postgres-backed store.
"""

import threading
from datetime import datetime
from typing import Any


class HITLStore:
    """Thread-safe in-memory store for sessions suspended at the HITL interrupt."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, dict[str, Any]] = {}

    def register(self, session_id: str, proposed_actions: list[dict]) -> None:
        """Register a session suspended at the HITL checkpoint."""
        with self._lock:
            self._sessions[session_id] = {
                "proposed_actions": proposed_actions,
                "registered_at": datetime.utcnow().isoformat(),
            }

    def get(self, session_id: str) -> dict[str, Any] | None:
        """Return the store entry for a session, or None if not found."""
        with self._lock:
            return self._sessions.get(session_id)

    def remove(self, session_id: str) -> None:
        """Remove a session from the store after approve or reject."""
        with self._lock:
            self._sessions.pop(session_id, None)

    def list_pending(self) -> list[str]:
        """Return a snapshot of all currently registered session IDs."""
        with self._lock:
            return list(self._sessions.keys())


# Singleton — import this object everywhere.
hitl_store = HITLStore()
