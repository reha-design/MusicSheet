"""Synchronous Celery adapters own one async runtime per delivery."""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace

import asyncpg
from redis.asyncio import Redis
from celery.exceptions import Retry,Reject

from musicsheet_storage import LocalStorage
from .contracts import InfrastructureUnavailable
from .events import RedisEventStore
from .providers import PROVIDERS
from .runner import run_stage

_logger=logging.getLogger(__name__)


async def _close_resources(connection,redis):
    if redis is not None:
        try:
            await asyncio.wait_for(redis.aclose(),2)
        except Exception:
            _logger.warning("Pipeline Redis cleanup failed")
    if connection is not None:
        try:
            await connection.close(timeout=5)
        except Exception:
            _logger.warning("Pipeline database cleanup failed")
            connection.terminate()


async def _owned_cleanup(coroutine):
    task=asyncio.create_task(coroutine)
    canceled=False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            canceled=True
    task.result()
    if canceled:
        raise asyncio.CancelledError from None


@asynccontextmanager
async def runtime(settings):
    connection=redis=None
    try:
        settings.require_ready()
        connection=await asyncpg.connect(settings.database_url,timeout=2,command_timeout=5)
        if settings.redis_url:
            redis=Redis.from_url(settings.redis_url,socket_connect_timeout=2,socket_timeout=2)
        yield SimpleNamespace(connection=connection,storage=LocalStorage(settings.local_storage_dir),
            providers=PROVIDERS,event_store=RedisEventStore(redis) if redis is not None else None)
    finally:
        await _owned_cleanup(_close_resources(connection,redis))


def execute_task(task,message,*,settings,runtime_factory=runtime,sleeper=time.sleep):
    async def execute():
        manager=runtime_factory(settings)
        resources=await manager.__aenter__()
        body_error=None
        try:
            await run_stage(message,connection=resources.connection,storage=resources.storage,
                providers=resources.providers,event_store=resources.event_store)
        except BaseException as error:
            body_error=error
            raise
        finally:
            try:
                await manager.__aexit__(type(body_error) if body_error else None,body_error,None)
            except Exception:
                # Cleanup cannot reverse an already committed stage.
                _logger.warning("Pipeline runtime cleanup failed")
    unavailable=False
    try:
        asyncio.run(execute())
    except Exception:
        unavailable=True
    if unavailable:
        try:
            task.retry(countdown=5,max_retries=None,exc=InfrastructureUnavailable())
        except Retry:
            raise
        except Exception:
            # Celery's retry may itself raise Reject(requeue=False) on publish failure.
            # Do not ACK; hold this delivery briefly before requesting redelivery.
            sleeper(5)
            raise Reject("Pipeline infrastructure is unavailable",requeue=True) from None
