"""
db/connection.py — Shared asyncpg connection pool.

Call configure(dsn) synchronously at startup (no event loop needed).
The pool is created lazily on the first call to db_connection(), in
whichever event loop is running at that time.

For MCP mode you may still call await init_pool(dsn) explicitly — it
is idempotent and will be a no-op if the pool is already initialised
for the current loop.
"""

import asyncio
from contextlib import asynccontextmanager
from typing import Optional

import asyncpg

_pool: Optional[asyncpg.Pool] = None
_configured_dsn: Optional[str] = None


def configure(dsn: str) -> None:
    """
    Store the DSN for lazy pool creation.  Call this once at startup
    (synchronous — no running event loop required).  The pool itself
    is created on the first db_connection() call inside the running loop.
    """
    global _configured_dsn
    _configured_dsn = dsn.replace("postgresql+asyncpg://", "postgresql://")


async def init_pool(dsn: str, min_size: int = 5, max_size: int = 20) -> None:
    """Create the module-level asyncpg pool. Called automatically by
    db_connection() if the pool is None; can also be called explicitly."""
    global _pool
    if _pool is not None:
        return  # already initialised — idempotent
    dsn = dsn.replace("postgresql+asyncpg://", "postgresql://")
    _pool = await asyncpg.create_pool(
        dsn=dsn,
        min_size=min_size,
        max_size=max_size,
        # Disable prepared-statement caching — prevents protocol state issues
        # when asyncio cancels a task mid-query and leaves the connection dirty.
        statement_cache_size=0,
        max_inactive_connection_lifetime=300.0,
    )


def get_pool() -> asyncpg.Pool:
    """Return the pool. Raises RuntimeError if not yet initialised."""
    if _pool is None:
        raise RuntimeError(
            "DB pool is not initialised. Call `await init_pool(dsn)` or "
            "`configure(dsn)` at startup before invoking any tool."
        )
    return _pool


@asynccontextmanager
async def db_connection():
    """
    Safely acquire and release a pool connection.

    If the pool has not been created yet (chat mode uses lazy init),
    creates it now in the current event loop using the DSN stored by
    configure().

    Handles asyncpg InterfaceError on release by force-terminating
    the connection so the pool discards and replaces it.
    """
    global _pool
    if _pool is None:
        if not _configured_dsn:
            raise RuntimeError(
                "No database DSN configured. Call configure(dsn) at startup."
            )
        await init_pool(_configured_dsn)

    pool = get_pool()
    conn = await pool.acquire()
    try:
        if conn.is_closed():
            raise asyncpg.InterfaceError("acquired a closed connection")
        yield conn
    finally:
        try:
            await pool.release(conn)
        except asyncpg.InterfaceError:
            # Connection left in a bad protocol state — terminate and discard it.
            try:
                conn.terminate()
            except Exception:
                pass


async def close_pool() -> None:
    """Close the pool at application shutdown."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
