"""Real Linux prefork worker checks. Unset opt-ins skip; configured failures fail."""
import asyncio

import pytest
from .support import live_harness

pytestmark=pytest.mark.celery_integration


@pytest.mark.parametrize("scenario",["normal","retry_once","duplicate","contend","kill","cancel","commit_failure","broker_failure"])
def test_real_worker_delivery_recovery_and_sse(tmp_path,scenario):
    asyncio.run(live_harness(tmp_path,scenario))
