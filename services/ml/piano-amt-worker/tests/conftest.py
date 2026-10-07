import hashlib
import wave

import pytest


@pytest.fixture
def audio(tmp_path):
    def create(*, channels=1, rate=16000, width=2, frames=1600):
        path = tmp_path/"input.wav"
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(channels)
            wav.setsampwidth(width)
            wav.setframerate(rate)
            wav.writeframes(b"\0"*(frames*channels*width))
        return path
    return create


@pytest.fixture
def checkpoint(tmp_path, monkeypatch):
    from musicsheet_piano_amt_worker import provenance
    path = tmp_path/"checkpoint.pth"
    path.write_bytes(b"abcd")
    monkeypatch.setattr(provenance, "CHECKPOINT_BYTES", 4)
    monkeypatch.setattr(provenance, "CHECKPOINT_MD5", hashlib.md5(b"abcd").hexdigest())
    return path, hashlib.sha256(b"abcd").hexdigest()


@pytest.fixture
def prediction():
    return dict(duration_sec=1.0, notes=[dict(pitch=60,onset=.1,offset=.5,velocity=80)],
                pedals=[dict(kind="sustain",onset=.2,offset=.9,value=127)],
                runtime=dict(torch_num_threads=1,torch_num_interop_threads=1))
