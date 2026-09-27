"""Operator entry point for explicit database migrations."""

import asyncio
import os
import sys

from .runner import MIGRATIONS, apply_migrations


def main() -> int:
    """Apply packaged migrations using the process DATABASE_URL."""
    try:
        database_url = os.environ["DATABASE_URL"]
    except KeyError:
        print("Migration failed: DATABASE_URL is required.", file=sys.stderr)
        return 1

    try:
        applied = asyncio.run(apply_migrations(database_url))
    except Exception:
        print("Migration failed. Check database availability and configuration.", file=sys.stderr)
        return 1

    current_version = max(migration.version for migration in MIGRATIONS)
    print(f"Applied versions: {applied}; current version: {current_version}")
    return 0
