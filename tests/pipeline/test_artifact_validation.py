import asyncio
import io
import traceback
import warnings
from uuid import uuid4

import pytest
from musicsheet_pipeline.artifacts import validate_artifacts
from musicsheet_pipeline.contracts import InvalidArtifact

from .runner_support import environment,IDENTITY,ROLE
from .support import JOB,OTHER


@pytest.mark.parametrize("case",["foreign","duplicate","hash","size","producer","version","prefix","uuid","mutated","missing"])
def test_invalid_output_is_sanitized_and_not_accepted(tmp_path,case):
    async def check():
        _,storage,_=environment(tmp_path)
        attempt=str(uuid4())
        ref=storage.put(JOB,f"attempt_{attempt}_out.wav",ROLE,io.BytesIO(b"abc"),"test","1")
        changes={"foreign":{"job_id":OTHER},"hash":{"sha256":"g"*64},"size":{"size_bytes":4},
                 "producer":{"producer":"secret-sentinel"},"version":{"producer_version":"2"},
                 "prefix":{"filename":"other.wav"},"uuid":{"id":"bad"},"mutated":{"role":"secret-sentinel"}}
        if case=="missing":
            storage.delete(ref)
        ref=ref.model_copy(update=changes.get(case,{}))
        refs=(ref,ref) if case=="duplicate" else (ref,)
        with warnings.catch_warnings(record=True) as captured:
            with pytest.raises(InvalidArtifact) as failure:
                await validate_artifacts(refs,job_id=JOB,identity=IDENTITY,storage=storage,
                    attempt_id=attempt,existing_inputs=(),cancellation=asyncio.Event())
        assert not captured and "secret-sentinel" not in "".join(traceback.format_exception(failure.value))
    asyncio.run(check())


def test_new_artifact_and_exact_existing_reference_are_valid(tmp_path):
    async def check():
        _,storage,original=environment(tmp_path)
        attempt=str(uuid4())
        new=storage.put(JOB,f"attempt_{attempt}_out.wav",ROLE,io.BytesIO(b"abc"),"test","1")
        assert await validate_artifacts((new,original),job_id=JOB,identity=IDENTITY,storage=storage,
            attempt_id=attempt,existing_inputs=(original,),cancellation=asyncio.Event())==(new,original)
    asyncio.run(check())
