"""Finite, secret-safe maintenance commands. Help never opens services."""
import argparse
import asyncio
import json
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace

import asyncpg
from redis.asyncio import Redis

from .config import PipelineSettings
from .events import RedisEventStore
from .maintenance import scan_stalled, fail_stalled
from .models import JobObservation, validate_stale_seconds
from .tasks import _owned_cleanup, _close_resources


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError("Invalid maintenance arguments")


def _arguments(argv):
    parser = _Parser(prog="musicsheet-maintenance")
    commands = parser.add_subparsers(dest="command", required=True)
    scan = commands.add_parser("scan")
    scan.add_argument("--stale-seconds", type=int, default=7200)
    scan.add_argument("--limit", type=int, default=100)
    fail = commands.add_parser("fail-stalled")
    fail.add_argument("--stale-seconds", type=int, default=7200)
    for name in ("job-id", "observed-status", "observed-stage", "observed-updated-at", "observed-attempt-id"):
        fail.add_argument("--"+name, required=True)
    args = parser.parse_args(argv)
    validate_stale_seconds(args.stale_seconds)
    if args.command == "scan":
        if not 1 <= args.limit <= 1000:
            raise ValueError
    else:
        args.observation = JobObservation(args.job_id, args.observed_status, args.observed_stage,
            datetime.fromisoformat(args.observed_updated_at),
            None if args.observed_attempt_id == "none" else args.observed_attempt_id)
    return args


@asynccontextmanager
async def _resources(settings, *, with_events=False):
    connection = redis = None
    try:
        connection = await asyncpg.connect(settings.database_url, timeout=2, command_timeout=5)
        if with_events and settings.redis_url:
            redis = Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2)
        yield SimpleNamespace(connection=connection, event_store=RedisEventStore(redis) if redis is not None else None)
    finally:
        await _owned_cleanup(_close_resources(connection, redis))


async def _run(settings, args, *, runtime_factory=_resources):
    async with runtime_factory(settings, with_events=args.command == "fail-stalled") as resources:
        if args.command == "scan":
            rows = await scan_stalled(resources.connection, stale_seconds=args.stale_seconds, limit=args.limit)
            print(json.dumps([row.to_dict() for row in rows]))
            return 0
        result = await fail_stalled(resources.connection, args.observation, stale_seconds=args.stale_seconds,
                                    event_store=resources.event_store)
        print(json.dumps(dict(job_id=args.observation.job_id, changed=result.changed, reason=result.reason,
            status=result.transition.job.status.value if result.transition else None)))
        return 0 if result.changed else 3


def main(argv=None):
    try:
        args = _arguments(argv)
    except ValueError:
        print("Invalid maintenance arguments", file=sys.stderr)
        return 2
    except SystemExit as error:
        return error.code
    try:
        settings = PipelineSettings.from_env()
        if not settings.database_url:
            raise ValueError
    except ValueError:
        print("Invalid maintenance configuration", file=sys.stderr)
        return 2
    try:
        return asyncio.run(_run(settings, args))
    except (Exception, KeyboardInterrupt):
        print("Pipeline maintenance is unavailable", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
