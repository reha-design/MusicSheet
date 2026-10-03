"""Dispatcher process entry; diagnostics never echo dependency credentials."""
import argparse
import asyncio
import math
import sys
from contextlib import asynccontextmanager

import asyncpg

from .config import PipelineSettings
from .dispatcher import CeleryPublisher,dispatch_once
from .outbox import recover_pending
from .tasks import _owned_cleanup,_close_resources


class _Parser(argparse.ArgumentParser):
    def error(self,message):
        raise ValueError("Invalid dispatcher arguments")


@asynccontextmanager
async def _connection(settings):
    connection=None
    try:
        connection=await asyncpg.connect(settings.database_url,timeout=2,command_timeout=5)
        yield connection
    finally:
        await _owned_cleanup(_close_resources(connection,None))


async def _run(settings,args,*,connection_factory=_connection,publisher_factory=CeleryPublisher):
    publisher=None
    try:
        if args.recover_pending:
            async with connection_factory(settings) as connection:
                while True:
                    async with connection.transaction():
                        count=await recover_pending(connection)
                    if count<100:
                        return 0
        publisher=publisher_factory(settings)
        while True:
            failed=False
            try:
                async with connection_factory(settings) as connection:
                    await dispatch_once(connection,publisher)
            except Exception:
                failed=True
            if failed:
                print("Pipeline dispatch is unavailable",file=sys.stderr)
            if args.once:
                return 1 if failed else 0
            await asyncio.sleep(args.poll_interval)
    finally:
        if publisher is not None:
            try:
                publisher.close()
            except Exception:
                print("Pipeline publisher cleanup failed",file=sys.stderr)


def main(argv=None):
    parser=_Parser(prog="musicsheet-dispatch")
    modes=parser.add_mutually_exclusive_group()
    modes.add_argument("--once",action="store_true")
    modes.add_argument("--recover-pending",action="store_true")
    parser.add_argument("--poll-interval",type=float,default=1)
    try:
        args=parser.parse_args(argv)
        if not math.isfinite(args.poll_interval) or args.poll_interval<=0:
            raise ValueError
    except ValueError:
        print("Invalid dispatcher arguments",file=sys.stderr)
        return 2
    except SystemExit as error:
        return error.code
    try:
        settings=PipelineSettings.from_env()
        settings.require_ready()
        return asyncio.run(_run(settings,args))
    except KeyboardInterrupt:
        return 0
    except Exception:
        print("Pipeline dispatch is unavailable",file=sys.stderr)
        return 1


if __name__=="__main__":
    raise SystemExit(main())
