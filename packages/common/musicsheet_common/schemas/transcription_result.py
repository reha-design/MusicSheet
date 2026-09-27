from typing import Literal

from pydantic import BaseModel, Field, field_validator

from musicsheet_common.schemas.note_events import PedalEvent, RawNoteEvent


class ProviderMetadata(BaseModel):
    id: str = Field(..., min_length=1)
    package_version: str = Field(..., min_length=1)
    source_commit: str = Field(..., min_length=1)
    model_asset: str = Field(..., min_length=1)
    supports_pedal: bool
    confidence_semantics: str = Field(..., min_length=1)


class TranscriptionResult(BaseModel):
    schema_version: Literal[1]
    provider: ProviderMetadata
    note_events: list[RawNoteEvent]
    pedal_events: list[PedalEvent]

    @field_validator("schema_version", mode="before")
    @classmethod
    def require_integer_schema_version(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("schema_version must be an integer")
        return value
