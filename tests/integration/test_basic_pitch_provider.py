"""Actual installed model through the product factory; no test-time installs."""
import asyncio
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from musicsheet_common import ArtifactRole, PipelineStage
from musicsheet_pipeline.config import PipelineSettings
from musicsheet_pipeline.providers import build_providers
from pipeline.basic_pitch_support import context, PROVENANCE

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests/fixtures/audio/basic_pitch_smoke.wav"
FIXTURE_SHA256 = "2970c7fca3ccc442c078eb0a4edb2f788731e9d36f5049cc2558fa68e599366a"


async def installed_provider(root):
    settings = PipelineSettings.from_env()
    assert settings.basic_pitch is not None, "Enable the installed Basic Pitch worker explicitly"
    providers = await build_providers(settings)
    provider = providers[PipelineStage.TRANSCRIBE]
    assert provider._setup_ok, "Installed worker/FFmpeg probes must succeed"
    return provider


def assert_results(storage, refs, attempt):
    assert len(refs) == 2
    assert {ref.role for ref in refs} == {ArtifactRole.RAW_TRANSCRIPTION, ArtifactRole.MIDI}
    for ref in refs:
        assert ref.filename.startswith(f"attempt_{attempt}_")
        assert ref.producer == "spotify-basic-pitch" and ref.producer_version == "0.1.0"
        with storage.open_read(ref) as stream:
            data = stream.read()
        assert len(data) == ref.size_bytes and hashlib.sha256(data).hexdigest() == ref.sha256
        if ref.role == ArtifactRole.RAW_TRANSCRIPTION:
            value = json.loads(data)
            assert value["provider"] == PROVENANCE and value["schema_version"] == 1
            assert value["note_events"] and value["pedal_events"] == []
        else:
            assert data.startswith(b"MThd") and len(data) > 14


@pytest.mark.ml_integration
def test_actual_product_provider_transcribes_cc0_fixture(tmp_path):
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == FIXTURE_SHA256
    async def run():
        provider = await installed_provider(tmp_path)
        ctx = context(tmp_path)
        with FIXTURE.open("rb") as stream:
            source = ctx.storage.put(ctx.message.job_id, "stem.wav", ArtifactRole.SEPARATED_AUDIO,
                stream, "test-fixture", "1")
        refs = await provider.run(replace(ctx, inputs=(source,)))
        assert_results(ctx.storage, refs, ctx.attempt_id)
    asyncio.run(run())
