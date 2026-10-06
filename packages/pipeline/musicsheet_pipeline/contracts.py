"""Validated, model-independent stage and provider contracts."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from uuid import UUID

from musicsheet_common import ArtifactRef, ArtifactRole, PipelineStage
from musicsheet_storage import ArtifactStorage

type JSONValue = None | bool | int | float | str | list[JSONValue] | dict[str, JSONValue]
STAGES = tuple(PipelineStage)


class InfrastructureUnavailable(Exception):
    def __init__(self):
        super().__init__("Pipeline infrastructure is unavailable")


class StageBusy(Exception):
    def __init__(self):
        super().__init__("Stage execution is already active")


class InvalidArtifact(ValueError):
    def __init__(self):
        super().__init__("Invalid stage artifact")


@dataclass(frozen=True)
class StageMessage:
    job_id: str
    stage: PipelineStage
    generation: int

    def __post_init__(self):
        try:
            if not isinstance(self.job_id, (str, UUID)) or type(self.generation) is not int or not 1 <= self.generation < 2**31:
                raise ValueError
            object.__setattr__(self, "job_id", str(UUID(str(self.job_id))))
            object.__setattr__(self, "stage", PipelineStage(self.stage))
        except (ValueError, TypeError, AttributeError):
            raise ValueError("Invalid stage message") from None

    def to_dict(self) -> dict[str, JSONValue]:
        return {"job_id": self.job_id, "stage": self.stage.value, "generation": self.generation}


@dataclass(frozen=True)
class ProviderIdentity:
    name: str
    version: str
    configuration: dict[str, JSONValue] = field(repr=False)
    input_roles: frozenset[ArtifactRole]
    output_roles: frozenset[ArtifactRole]
    configuration_json: str = field(init=False, repr=False)

    def __post_init__(self):
        try:
            if not isinstance(self.name, str) or not 1 <= len(self.name) <= 64 or not isinstance(self.version, str) or not 1 <= len(self.version) <= 32:
                raise ValueError
            if not isinstance(self.configuration, dict):
                raise ValueError
            text = json.dumps(self.configuration, sort_keys=True, separators=(",", ":"), allow_nan=False)
            if len(text.encode("utf-8")) > 65536:
                raise ValueError
            object.__setattr__(self, "configuration_json", text)
            object.__setattr__(self, "configuration", json.loads(text))
            object.__setattr__(self, "input_roles", frozenset(ArtifactRole(r) for r in self.input_roles))
            object.__setattr__(self, "output_roles", frozenset(ArtifactRole(r) for r in self.output_roles))
        except (ValueError, TypeError, OverflowError, RecursionError):
            raise ValueError("Invalid provider identity") from None


@dataclass(frozen=True)
class StageInput:
    message: StageMessage
    attempt_id: str
    source_type: str
    source_url: str | None = field(repr=False)
    target_instrument: str | None
    inputs: tuple[ArtifactRef, ...] = field(repr=False)


@dataclass(frozen=True)
class StageContext(StageInput):
    storage: ArtifactStorage = field(repr=False)
    cancellation: asyncio.Event = field(repr=False)
