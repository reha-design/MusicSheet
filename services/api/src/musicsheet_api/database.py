"""Optional PostgreSQL pool for API request-time persistence."""

import logging

import asyncpg


logger = logging.getLogger(__name__)


async def create_optional_pool(database_url: str | None) -> asyncpg.Pool | None:
    if not database_url:
        return None
    try:
        return await asyncpg.create_pool(dsn=database_url, timeout=1.0, min_size=1)
    except Exception:
        logger.warning("PostgreSQL pool unavailable at startup")
        return None
