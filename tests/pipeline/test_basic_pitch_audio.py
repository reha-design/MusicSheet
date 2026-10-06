import asyncio
import io
import os
from pathlib import Path
import shutil
import struct
import sys
import wave

import pytest

from musicsheet_common import ArtifactRole
from musicsheet_pipeline.basic_pitch import audio
from musicsheet_pipeline.config import BasicPitchSettings
from musicsheet_pipeline.contracts import InvalidArtifact
from .basic_pitch_support import context

FFMPEG = os.environ.get("FFMPEG_EXECUTABLE") or shutil.which("ffmpeg")


def pcm(*, rate=22050, channels=1, empty=False):
    stream = io.BytesIO()
    with wave.open(stream, "wb") as output:
        output.setparams((channels, 2, rate, 0, "NONE", "not compressed"))
        output.writeframes(b"\x00\x00" * channels * (0 if empty else 2205))
    return stream.getvalue()


def float_wav():
    fmt = struct.pack("<HHIIHH", 3, 2, 44100, 44100 * 8, 8, 32)
    samples = struct.pack("<f", .1) * 2 * 4410
    body = b"WAVEfmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(samples)) + samples
    return b"RIFF" + struct.pack("<I", len(body)) + body


def prepare(tmp_path, contents, *, role=ArtifactRole.SEPARATED_AUDIO):
    ctx = context(tmp_path)
    ref = ctx.storage.put(ctx.message.job_id, "stem.wav", role, io.BytesIO(contents), "test", "1")
    from dataclasses import replace
    ctx = replace(ctx, inputs=(ref,))
    work = tmp_path / "work"
    work.mkdir()
    settings = BasicPitchSettings(Path(sys.executable), Path(FFMPEG) if FFMPEG else tmp_path / "missing-ffmpeg")
    return ctx, work, settings


def test_22050_mono_pcm_skips_conversion(tmp_path, monkeypatch):
    async def unexpected(*args, **kwargs):
        raise AssertionError("conversion should be skipped")
    monkeypatch.setattr(audio, "run_owned_process", unexpected)
    ctx, work, settings = prepare(tmp_path, pcm())
    result = asyncio.run(audio.prepare_input(ctx, work, settings))
    assert result.read_bytes() == pcm()


@pytest.mark.skipif(not FFMPEG, reason="FFmpeg executable is required for real conversion")
@pytest.mark.parametrize("contents", [pcm(rate=44100, channels=2), float_wav()], ids=["stereo-pcm", "stereo-float"])
def test_noncanonical_wav_is_converted_to_22050_mono_pcm(tmp_path, contents):
    ctx, work, settings = prepare(tmp_path, contents)
    result = asyncio.run(audio.prepare_input(ctx, work, settings))
    with wave.open(str(result), "rb") as output:
        assert (output.getframerate(), output.getnchannels(), output.getsampwidth()) == (22050, 1, 2)
        assert output.getnframes() > 0
        assert len(output.readframes(output.getnframes())) == output.getnframes() * 2


@pytest.mark.parametrize("contents", [b"not-wav", pcm(empty=True), pcm()[:-2], float_wav()[:-4],
    b"RIFF\xff\xff\xff\xffWAVE", b"RIFF\x05\x00\x00\x00WAVEJ"],
    ids=["magic", "empty", "truncated-pcm", "truncated-float", "container-size", "chunk-header"])
def test_invalid_or_truncated_wav_fails_before_external_tool(tmp_path, contents, monkeypatch):
    called = []
    async def external(*args, **kwargs):
        called.append(args)
        raise AssertionError("must reject before conversion/model")
    monkeypatch.setattr(audio, "run_owned_process", external)
    ctx, work, settings = prepare(tmp_path, contents)
    with pytest.raises(InvalidArtifact):
        asyncio.run(audio.prepare_input(ctx, work, settings))
    assert called == []


@pytest.mark.parametrize("case", ["wrong-role", "empty", "two"])
def test_input_role_and_count_are_exact(tmp_path, case):
    from dataclasses import replace
    ctx, work, settings = prepare(tmp_path, pcm(), role=ArtifactRole.MIDI if case == "wrong-role" else ArtifactRole.SEPARATED_AUDIO)
    if case in {"empty", "two"}:
        ctx = replace(ctx, inputs=() if case == "empty" else ctx.inputs * 2)
    with pytest.raises(InvalidArtifact):
        asyncio.run(audio.prepare_input(ctx, work, settings))
