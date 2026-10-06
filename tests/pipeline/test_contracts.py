import pytest
from pathlib import Path

from musicsheet_common import PipelineStage
from musicsheet_pipeline.contracts import StageMessage, ProviderIdentity

JOB = "00000000-0000-4000-8000-000000000001"


def test_provider_config_is_opt_in_and_preserves_five_argument_constructor(tmp_path):
    from musicsheet_pipeline.config import PipelineSettings
    assert PipelineSettings(None, None, None, None, tmp_path).basic_pitch is None
    configured = PipelineSettings.from_env({"TRANSCRIPTION_PROVIDER": "basic-pitch",
        "BASIC_PITCH_PYTHON": str(tmp_path / "python"), "FFMPEG_EXECUTABLE": str(tmp_path / "ffmpeg")})
    assert configured.basic_pitch.python == tmp_path / "python"
    assert configured.basic_pitch.ffmpeg == tmp_path / "ffmpeg"
    for env in ({"TRANSCRIPTION_PROVIDER": "unknown"},
                {"TRANSCRIPTION_PROVIDER": "basic-pitch"},
                {"TRANSCRIPTION_PROVIDER": "basic-pitch", "BASIC_PITCH_PYTHON": "relative",
                 "FFMPEG_EXECUTABLE": str(tmp_path / "ffmpeg")}):
        with pytest.raises(ValueError):
            PipelineSettings.from_env(env)


@pytest.mark.parametrize("generation", [True, False, 0, -1, 1.0, "1", None, 2**31])
def test_contract_rejects_invalid_generation(generation):
    with pytest.raises(ValueError, match="Invalid stage message"):
        StageMessage(JOB, PipelineStage.DOWNLOAD, generation)


def test_contract_rejects_boolean_generation():
    with pytest.raises(ValueError):
        StageMessage(JOB, PipelineStage.DOWNLOAD, True)


@pytest.mark.parametrize("job,stage", [("secret", "DOWNLOAD"), (JOB, "invalid"), (True, "DOWNLOAD")])
def test_contract_rejects_invalid_identity(job, stage):
    with pytest.raises(ValueError) as failure:
        StageMessage(job, stage, 1)
    assert "secret" not in str(failure.value)


def test_message_canonicalizes_and_contains_only_dispatch_fields():
    message = StageMessage(JOB.replace("-", ""), "DOWNLOAD", 1)
    assert message.to_dict() == {"job_id": JOB, "stage": "DOWNLOAD", "generation": 1}


@pytest.mark.parametrize("name,version,config", [("x"*65,"1",{}), ("p","x"*33,{}), ("p","1",{"a":float("nan")}), ("p","1",{"a":"x"*65536})])
def test_provider_rejects_invalid_identity_and_configuration(name, version, config):
    with pytest.raises(ValueError, match="Invalid provider identity"):
        ProviderIdentity(name, version, config, frozenset(), frozenset())
