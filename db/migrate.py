"""
db/migrate.py — Apply all migration files against the ops_agent database.

Usage:
    python -m db.migrate
"""

import asyncio
import pathlib

import asyncpg

# Import settings to get database_url — handle missing env gracefully at module import
try:
    from config import settings
    _DATABASE_URL = settings.database_url
except Exception:
    import os
    _DATABASE_URL = os.environ.get("DATABASE_URL", "")

MIGRATIONS_DIR = pathlib.Path(__file__).parent / "migrations"

MIGRATION_FILES = [
    "001_public_schema.sql",
    "002_store_schema.sql",
]


async def run_migrations(dsn: str) -> None:
    # asyncpg expects postgresql:// not postgresql+asyncpg://
    dsn = dsn.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn=dsn)
    try:
        for filename in MIGRATION_FILES:
            path = MIGRATIONS_DIR / filename
            sql = path.read_text(encoding="utf-8")
            print(f"[migrate] Applying {filename} …")
            await conn.execute(sql)
            print(f"[migrate] {filename} — OK")
    finally:
        await conn.close()


def main() -> None:
    if not _DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not set. Add it to your .env file or set the "
            "environment variable before running db.migrate."
        )
    asyncio.run(run_migrations(_DATABASE_URL))
    print("[migrate] All migrations applied successfully.")


if __name__ == "__main__":
    main()
