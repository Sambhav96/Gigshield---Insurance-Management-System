"""
core/migrations.py — Auto-run SQL migrations on startup.

Tracks applied migrations in a _migrations table so each file runs exactly once.
Called from main.py startup event before the app begins serving requests.
"""
from __future__ import annotations

import asyncpg
import structlog
from pathlib import Path

log = structlog.get_logger()


async def run_migrations(conn: asyncpg.Connection) -> None:
    """
    Apply all pending *.sql files from supabase/migrations/ in alphabetical order.
    Idempotent — already-applied migrations are skipped.
    Raises on any migration failure so the app refuses to start with a broken schema.
    """
    migrations_dir = Path(__file__).parent.parent.parent / "supabase" / "migrations"

    # Create migration tracking table if not exists
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS _migrations (
            id        SERIAL PRIMARY KEY,
            filename  TEXT UNIQUE NOT NULL,
            applied_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    applied: set[str] = {
        row["filename"]
        for row in await conn.fetch("SELECT filename FROM _migrations ORDER BY filename")
    }

    migration_files = sorted(migrations_dir.glob("*.sql"))
    if not migration_files:
        log.warning("migrations_dir_empty", path=str(migrations_dir))
        return

    for mf in migration_files:
        fname = mf.name
        if fname in applied:
            log.info("migration_already_applied", file=fname)
            continue

        log.info("migration_applying", file=fname)
        sql = mf.read_text(encoding="utf-8")

        try:
            await conn.execute(sql)
            await conn.execute(
                "INSERT INTO _migrations (filename) VALUES ($1)", fname
            )
            log.info("migration_applied_ok", file=fname)
        except asyncpg.PostgresError as exc:
            # If the object already exists (e.g. re-run against non-empty DB), log and continue.
            msg = str(exc).lower()
            if "already exists" in msg or "duplicate" in msg:
                log.warning("migration_skipped_already_exists", file=fname, detail=str(exc))
                # Still record it as applied so we don't retry next time
                try:
                    await conn.execute(
                        "INSERT INTO _migrations (filename) VALUES ($1) ON CONFLICT DO NOTHING", fname
                    )
                except Exception:
                    pass
            else:
                log.error("migration_failed", file=fname, error=str(exc))
                raise
