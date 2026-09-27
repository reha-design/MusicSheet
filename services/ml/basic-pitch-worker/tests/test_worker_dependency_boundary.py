import importlib.metadata as metadata
import importlib.util
import json
import sys

import pytest


EXPECTED_BASIC_PITCH_VERSION = "0.4.0"
EXPECTED_BASIC_PITCH_SOURCE_COMMIT = "049dc8a01a170c2370d7b246ec1c2067e060c3bf"
EXPECTED_BASIC_PITCH_SOURCE_URL = "https://github.com/spotify/basic-pitch"


def _installed_distribution_names() -> set[str]:
    return {
        (distribution.metadata.get("Name") or "").lower().replace("_", "-")
        for distribution in metadata.distributions()
    }


def test_worker_runs_on_python_312():
    assert sys.version_info[:2] == (3, 12)


def test_cpu_onnx_runtime_is_available():
    import onnxruntime

    assert "CPUExecutionProvider" in onnxruntime.get_available_providers()


def test_basic_pitch_selects_bundled_onnx_backend():
    import basic_pitch

    assert basic_pitch.TF_PRESENT is False
    assert basic_pitch.ONNX_PRESENT is True


def test_basic_pitch_inference_api_is_importable():
    from basic_pitch.inference import predict

    assert callable(predict)


def test_tensorflow_is_not_installed():
    installed = _installed_distribution_names()
    tensorflow_distributions = {
        "tensorflow",
        "tensorflow-intel",
        "tensorflow-cpu",
        "tensorflow-macos",
    }

    assert installed.isdisjoint(tensorflow_distributions)
    assert importlib.util.find_spec("tensorflow") is None


def test_musicsheet_common_is_not_installed_or_importable():
    installed = _installed_distribution_names()

    assert "musicsheet-common" not in installed
    assert importlib.util.find_spec("musicsheet_common") is None


def test_basic_pitch_version_and_installed_source_match_pins():
    from musicsheet_basic_pitch_worker import provenance

    distribution = metadata.distribution("basic-pitch")
    direct_url_text = distribution.read_text("direct_url.json")

    assert distribution.version == EXPECTED_BASIC_PITCH_VERSION
    assert provenance.BASIC_PITCH_PACKAGE_VERSION == EXPECTED_BASIC_PITCH_VERSION
    assert provenance.BASIC_PITCH_SOURCE_COMMIT == EXPECTED_BASIC_PITCH_SOURCE_COMMIT
    assert provenance.BASIC_PITCH_SOURCE_URL == EXPECTED_BASIC_PITCH_SOURCE_URL
    assert provenance.BASIC_PITCH_PROVIDER_ID == "spotify-basic-pitch"
    assert provenance.BASIC_PITCH_MODEL_ASSET == "nmp.onnx"
    assert provenance.BASIC_PITCH_SUPPORTS_PEDAL is False
    assert provenance.BASIC_PITCH_CONFIDENCE_SEMANTICS == "uncalibrated_note_activation_mean"
    assert direct_url_text is not None

    direct_url = json.loads(direct_url_text)
    assert direct_url["url"].rstrip("/") == EXPECTED_BASIC_PITCH_SOURCE_URL
    assert direct_url["vcs_info"]["commit_id"] == EXPECTED_BASIC_PITCH_SOURCE_COMMIT


def test_tensorflow_is_not_a_resolvable_distribution():
    with pytest.raises(metadata.PackageNotFoundError):
        metadata.version("tensorflow")
