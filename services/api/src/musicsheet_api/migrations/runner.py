"""Apply schema migrations on one locked PostgreSQL session."""

from collections.abc import Sequence
from dataclasses import dataclass

import asyncpg

from .v0001_initial import UPGRADE_SQL as INITIAL_UPGRADE_SQL
from .v0002_pipeline import UPGRADE_SQL as PIPELINE_UPGRADE_SQL


@dataclass(frozen=True)
class Migration:
    version: int
    upgrade_sql: str


MIGRATIONS: tuple[Migration, ...] = (Migration(1, INITIAL_UPGRADE_SQL), Migration(2, PIPELINE_UPGRADE_SQL))

# A fixed, application-specific signed bigint for PostgreSQL's session lock.
_MIGRATION_LOCK_KEY = 0x4D55534943534854


async def apply_migrations(
    database_url: str, *, migrations: Sequence[Migration] | None = None
) -> list[int]:
    """Apply pending migrations and return their newly recorded versions."""
    connection = await asyncpg.connect(database_url)
    locked = False
    try:
        await connection.execute("SELECT pg_advisory_lock($1)", _MIGRATION_LOCK_KEY)
        locked = True
        await connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY, "
            "applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        rows = await connection.fetch("SELECT version FROM schema_migrations")
        applied = {row["version"] for row in rows}
        newly_applied: list[int] = []
        selected = MIGRATIONS if migrations is None else migrations
        for migration in sorted(selected, key=lambda item: item.version):
            if migration.version in applied:
                continue
            async with connection.transaction():
                await connection.execute(migration.upgrade_sql)
                await connection.execute(
                    "INSERT INTO schema_migrations (version) VALUES ($1)",
                    migration.version,
                )
            newly_applied.append(migration.version)
            applied.add(migration.version)
        return newly_applied
    finally:
        try:
            if locked:
                await connection.execute("SELECT pg_advisory_unlock($1)", _MIGRATION_LOCK_KEY)
        finally:
            await connection.close()
