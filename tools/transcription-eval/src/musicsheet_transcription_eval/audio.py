"""Shared PCM crop/downmix and explicit FFmpeg swr resampling receipts."""

import asyncio
import hashlib
from pathlib import Path
import shutil
import tempfile
import time
import wave

import numpy as np
import soundfile as sf
from musicsheet_pipeline.basic_pitch.io import check_stop, run_owned_io
from musicsheet_pipeline.basic_pitch.process import run_owned_process

from .contracts import AudioPreparationReceipt, PreparedAudio, integer
from .manifest import digest_file, regular_file, safe_path

PCM_REVISION = "w05-pcm-r2"


def downmix(samples: np.ndarray) -> np.ndarray:
    if samples.dtype != np.int16 or samples.ndim != 2 or samples.shape[1] != 2: raise ValueError("expected PCM16 stereo")
    values = samples.astype(np.float64) / 32768.
    return (values[:, 0] + values[:, 1]) / 2.


def pcm16(samples: np.ndarray) -> np.ndarray:
    if samples.ndim != 1 or not np.all(np.isfinite(samples)): raise ValueError("invalid mono samples")
    return np.clip(np.rint(np.clip(samples, -1., 1.) * 32768.), -32768, 32767).astype("<i2")


async def prepare_audio(source: Path, *, start_sec: int, destination: Path, ffmpeg: Path, cancellation: asyncio.Event) -> PreparedAudio:
    if cancellation.is_set(): raise asyncio.CancelledError
    integer(start_sec, 0)
    started = time.monotonic()
    source, destination, ffmpeg = source.absolute(), destination.absolute(), ffmpeg.absolute()
    regular_file(source, maximum=2 * 1024 ** 3)
    regular_file(ffmpeg)
    safe_path(destination.parent, destination.name)
    if destination.exists(): raise ValueError("prepared destination already exists")
    destination.mkdir(parents=True)
    work = Path(tempfile.mkdtemp(prefix="owned-", dir=destination))
    committed = []
    success = False
    try:
        mono = work / "mono.wav"
        def crop(stop):
            with sf.SoundFile(source) as incoming:
                rate = incoming.samplerate
                frames, start = 30 * rate, start_sec * rate
                if incoming.format not in {"WAV", "WAVEX"} or incoming.subtype != "PCM_16" or incoming.channels != 2 or start + frames > incoming.frames:
                    raise ValueError("source PCM16 stereo/crop mismatch")
                incoming.seek(start)
                digest, remaining = hashlib.sha256(), frames
                with sf.SoundFile(mono, "w", samplerate=rate, channels=1, format="WAV", subtype="DOUBLE", endian="LITTLE") as outgoing:
                    while remaining:
                        check_stop(stop)
                        samples = incoming.read(min(65536, remaining), dtype="int16", always_2d=True)
                        if not len(samples): raise ValueError("truncated source crop")
                        digest.update(samples.astype("<i2", copy=False).tobytes())
                        outgoing.write(downmix(samples)); remaining -= len(samples)
            return rate, frames, start, digest.hexdigest(), digest_file(mono, stop=stop)
        rate, frames, start_frame, crop_hash, mono_hash = await run_owned_io(crop, cancellation=cancellation)
        version = await run_owned_process((str(ffmpeg), "-version"), cwd=work, cancellation=cancellation, timeout=30, capture_stdout=True)
        if version.returncode: raise ValueError("FFmpeg version failed")
        version_line = version.stdout.decode("utf-8", errors="strict").splitlines()[0]
        commands, outputs = [], []
        for label, target_rate in (("basic", 22050), ("piano", 16000)):
            intermediate, final = work / f"{label}-double.wav", work / f"{label}.wav"
            command = (str(ffmpeg), "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(mono),
                "-af", f"aresample={target_rate}:resampler=swr:filter_size=32:phase_shift=10:linear_interp=1:cutoff=0.97:osf=dbl:dither_method=none",
                "-map_metadata", "-1", "-c:a", "pcm_f64le", "-flags:a", "+bitexact", str(intermediate))
            result = await run_owned_process(command, cwd=work, cancellation=cancellation, timeout=300)
            if result.returncode: raise ValueError("FFmpeg resampling failed")
            def convert(stop):
                regular_file(intermediate, maximum=30 * target_rate * 8 + 4096)
                with sf.SoundFile(intermediate) as incoming:
                    if (incoming.channels, incoming.samplerate, incoming.frames, incoming.subtype) != (1, target_rate, 30 * target_rate, "DOUBLE"):
                        raise ValueError("resampling frame/format mismatch")
                    with wave.open(str(final), "wb") as outgoing:
                        outgoing.setnchannels(1); outgoing.setsampwidth(2); outgoing.setframerate(target_rate)
                        remaining = incoming.frames
                        while remaining:
                            check_stop(stop)
                            values = incoming.read(min(65536, remaining), dtype="float64")
                            if not len(values): raise ValueError("truncated resampling output")
                            outgoing.writeframesraw(pcm16(values).tobytes()); remaining -= len(values)
                check_stop(stop)
            await run_owned_io(convert, cancellation=cancellation)
            commands.append(command); outputs.append(final)
        receipt = AudioPreparationReceipt(crop_hash, mono_hash, rate, frames, start_frame, 661500, 480000, version_line, tuple(commands), PCM_REVISION, time.monotonic() - started)
        def commit(stop):
            for path in outputs:
                check_stop(stop)
                target = safe_path(destination, path.name)
                if target.exists(): raise ValueError("output overwrite refused")
                # A move preserves mkdtemp's private Windows DACL. Create under
                # the ordinary destination to inherit its intended access.
                with path.open("rb") as incoming, target.open("xb") as outgoing:
                    committed.append(target)
                    while True:
                        check_stop(stop)
                        chunk = incoming.read(65536)
                        if not chunk: break
                        outgoing.write(chunk)
            check_stop(stop)
        await run_owned_io(commit, cancellation=cancellation)
        success = True
        return PreparedAudio(committed[0], committed[1], receipt)
    finally:
        if not work.resolve().is_relative_to(destination.resolve()): raise ValueError("owned cleanup path escaped")
        shutil.rmtree(work)
        if not success:
            for path in committed: path.unlink(missing_ok=True)
            destination.rmdir()
