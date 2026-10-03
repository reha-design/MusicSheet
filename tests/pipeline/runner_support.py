import io

from musicsheet_common import ArtifactRole
from musicsheet_pipeline.contracts import ProviderIdentity
from musicsheet_storage import LocalStorage

from .support import JOB, Connection

ROLE=ArtifactRole.SOURCE_ORIGINAL
IDENTITY=ProviderIdentity("test","1",{},frozenset({ROLE}),frozenset({ROLE}))


def environment(tmp_path):
    c=Connection()
    storage=LocalStorage(tmp_path)
    original=storage.put(JOB,"source.wav",ROLE,io.BytesIO(b"abc"),"upload","1")
    c.db.artifacts={original.id:original.model_dump()}
    return c,storage,original


class Provider:
    identity=IDENTITY
    def __init__(self, *, error=None, action=None):
        self.calls=[]
        self.error=error
        self.action=action
    async def run(self,context):
        self.calls.append(context)
        if self.error:
            raise self.error
        if self.action:
            return await self.action(context)
        return context.inputs


class Events:
    def __init__(self,c, *, error=None):
        self.c=c
        self.error=error
        self.events=[]
        self.committed=[]
    async def publish(self,event):
        self.committed.append(self.c.db.jobs[JOB]["status"]==event.status.value and not self.c.in_transaction)
        self.events.append(event)
        if self.error:
            raise self.error
        return "1-0"
