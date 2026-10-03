"""Provider boundary. Deployment starts with no processing providers configured."""
from types import MappingProxyType
from typing import Mapping,Protocol

from musicsheet_common import ArtifactRef,PipelineStage
from .contracts import ProviderIdentity,StageContext


class RetryableProviderError(Exception):
    def __init__(self):
        super().__init__("Stage provider requests retry")


class PermanentProviderError(Exception):
    def __init__(self):
        super().__init__("Stage provider failed")


class StageProvider(Protocol):
    identity: ProviderIdentity
    async def run(self,context: StageContext) -> tuple[ArtifactRef,...]: ...


PROVIDERS: Mapping[PipelineStage,StageProvider]=MappingProxyType({})
