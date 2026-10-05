import asyncio
import shutil

import numpy as np
import pytest
import soundfile as sf

from musicsheet_transcription_eval.audio import downmix, pcm16, prepare_audio


def test_antiphase_downmix_is_zero():
    samples = np.array([[32767, -32767], [-32768, 32767], [0, 0]], dtype=np.int16)
    assert downmix(samples).tolist() == [0., -1. / 65536, 0.]


def test_half_sample_rounding_clip_and_saturation():
    samples = np.array([.5, 1.5, 2.5, -.5, -1.5, -2.5]) / 32768
    assert pcm16(samples).tolist() == [0, 2, 2, 0, -2, -2]
    assert pcm16(np.array([-2., 2.])).tolist() == [-32768, 32767]
    with pytest.raises(ValueError): pcm16(np.array([float("nan")]))


def test_actual_ffmpeg_thirty_second_frames_and_receipt(tmp_path):
    executable = shutil.which("ffmpeg")
    if not executable: pytest.skip("FFmpeg not installed")
    source = tmp_path / "source.wav"
    sf.write(source, np.zeros((31 * 1000, 2), dtype=np.int16), 1000, subtype="PCM_16")
    result = asyncio.run(prepare_audio(source, start_sec=1, destination=tmp_path / "prepared", ffmpeg=__import__("pathlib").Path(executable), cancellation=asyncio.Event()))
    for path, rate, frames in ((result.basic_audio, 22050, 661500), (result.piano_audio, 16000, 480000)):
        with sf.SoundFile(path) as f: assert (f.samplerate, f.channels, f.subtype, f.frames) == (rate, 1, "PCM_16", frames)
    assert result.receipt.start_frame == 1000
    assert result.receipt.source_frames == 30000
    assert result.receipt.ffmpeg_version.startswith("ffmpeg version")
    assert len(result.receipt.argv) == 2
    assert not list(result.basic_audio.parent.glob("*.part"))


def test_windows_final_audio_inherits_workspace_directory_access(tmp_path):
    import os
    import subprocess
    import uuid
    from pathlib import Path
    if os.name != "nt": pytest.skip("Windows ACL regression")
    powershell = shutil.which("pwsh")
    if not powershell: pytest.skip("PowerShell 7 required for Windows ACL probe")
    executable = shutil.which("ffmpeg")
    if not executable: pytest.skip("FFmpeg not installed")
    workspace_outputs = Path(__file__).parents[3] / "outputs/.verification-w05"
    ordinary = workspace_outputs / ("acl-access-" + uuid.uuid4().hex)
    ordinary.mkdir()
    try:
        source = tmp_path / "source.wav"
        sf.write(source, np.zeros((30000, 2), dtype=np.int16), 1000, subtype="PCM_16")
        result = asyncio.run(prepare_audio(source, start_sec=0, destination=ordinary / "prepared", ffmpeg=Path(executable), cancellation=asyncio.Event()))
        control = result.basic_audio.parent / "access-control.txt"
        control.write_bytes(b"control")
        def principals(path):
            probe = subprocess.run([powershell, "-NoProfile", "-Command", "[System.IO.FileSystemAclExtensions]::GetAccessControl([System.IO.FileInfo]::new($env:W05_ACL_PATH)).GetAccessRules($true,$true,[System.Security.Principal.SecurityIdentifier]).IdentityReference.Value | Sort-Object -Unique"], env={**os.environ, "W05_ACL_PATH": str(path)}, capture_output=True, text=True, timeout=30)
            assert probe.returncode == 0, probe.stderr
            result = set(probe.stdout.splitlines())
            assert result
            return result
        assert principals(result.basic_audio) == principals(control)
        assert principals(result.piano_audio) == principals(control)
    finally:
        assert ordinary.resolve().is_relative_to(workspace_outputs.resolve())
        shutil.rmtree(ordinary)


@pytest.mark.parametrize("subtype,channels", [("FLOAT", 2), ("PCM_16", 1)])
def test_source_subtype_or_channels_rejected(tmp_path, subtype, channels):
    source = tmp_path / "source.wav"
    sf.write(source, np.zeros((31000, channels)), 1000, subtype=subtype)
    with pytest.raises(ValueError): asyncio.run(prepare_audio(source, start_sec=0, destination=tmp_path / "prepared", ffmpeg=__import__("pathlib").Path(shutil.which("ffmpeg") or "invalid"), cancellation=asyncio.Event()))


def test_cancelled_audio_has_no_outputs(tmp_path):
    cancel = asyncio.Event(); cancel.set()
    with pytest.raises(asyncio.CancelledError): asyncio.run(prepare_audio(tmp_path / "missing", start_sec=0, destination=tmp_path / "prepared", ffmpeg=tmp_path / "fake", cancellation=cancel))
    assert not (tmp_path / "prepared").exists()


def test_final_copy_io_failure_rolls_back_both_outputs(tmp_path, monkeypatch):
    from pathlib import Path
    executable = shutil.which("ffmpeg")
    if not executable: pytest.skip("FFmpeg not installed")
    source = tmp_path / "source.wav"
    sf.write(source, np.zeros((30000, 2), dtype=np.int16), 1000, subtype="PCM_16")
    destination = tmp_path / "prepared"
    original = Path.open
    class BrokenWriter:
        def __init__(self, file): self.file = file
        def __enter__(self): return self
        def __exit__(self, *args): self.file.close()
        def write(self, data):
            self.file.write(data[:17])
            raise OSError("fixture write failure")
    def open_file(path, mode="r", *args, **kwargs):
        file = original(path, mode, *args, **kwargs)
        return BrokenWriter(file) if path == destination / "piano.wav" and mode == "xb" else file
    monkeypatch.setattr(Path, "open", open_file)
    with pytest.raises(OSError, match="fixture write failure"):
        asyncio.run(prepare_audio(source, start_sec=0, destination=destination, ffmpeg=Path(executable), cancellation=asyncio.Event()))
    assert not destination.exists()


@pytest.mark.parametrize("mode", ["second_failure", "cancel_child", "crop_outside"])
def test_audio_partial_failure_and_inflight_cancel_cleanup(tmp_path, monkeypatch, mode):
    from pathlib import Path
    from musicsheet_transcription_eval import audio
    executable = shutil.which("ffmpeg")
    if not executable: pytest.skip("FFmpeg not installed")
    source = tmp_path / "source.wav"
    sf.write(source, np.zeros((31000, 2), dtype=np.int16), 1000, subtype="PCM_16")
    cancellation, calls = asyncio.Event(), []
    original = audio.run_owned_process
    async def process(argv, **kwargs):
        calls.append(argv)
        if mode == "cancel_child" and len(calls) == 2:
            cancellation.set()
            return await original((__import__("sys").executable, "-c", "import time; time.sleep(60)"), **kwargs)
        if mode == "second_failure" and len(calls) == 3:
            return await original((str(executable), "-invalid-fixture-option"), **kwargs)
        return await original(argv, **kwargs)
    monkeypatch.setattr(audio, "run_owned_process", process)
    expected = asyncio.CancelledError if mode == "cancel_child" else ValueError
    with pytest.raises(expected):
        asyncio.run(prepare_audio(source, start_sec=2 if mode == "crop_outside" else 0, destination=tmp_path / "prepared", ffmpeg=Path(executable), cancellation=cancellation))
    assert not (tmp_path / "prepared").exists()
