import asyncio
import pytest
from musicsheet_pipeline.contracts import StageMessage
from musicsheet_pipeline.outbox import enqueue_stage, recover_pending
from .support import Connection, JOB, OTHER


@pytest.mark.parametrize("delay", [True,-1,1,5.0,11])
def test_invalid_delay_has_no_database_effect(delay):
    c=Connection()
    with pytest.raises(ValueError):
        asyncio.run(enqueue_stage(c,StageMessage(JOB,"DOWNLOAD",1),delay_seconds=delay))
    assert not c.queries


@pytest.mark.parametrize("limit", [True,0,101,1.0])
def test_invalid_recovery_limit_has_no_database_effect(limit):
    c=Connection()
    with pytest.raises(ValueError):
        asyncio.run(recover_pending(c,limit=limit))
    assert not c.queries


@pytest.mark.parametrize("status", ["RUNNING","RETRYING","CANCEL_REQUESTED","CANCELED","COMPLETED","FAILED"])
def test_recovery_does_not_schedule_nonpending_jobs(status):
    c=Connection()
    c.db.jobs[JOB]["status"]=status
    assert asyncio.run(recover_pending(c))==0 and not c.db.outbox
