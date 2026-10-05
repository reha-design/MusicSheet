import io
import re
import threading
import zipfile

import httpx
import pytest

from musicsheet_transcription_eval.range_io import RangeReader


class SparseFile:
    def __init__(self): self.position, self.size, self.parts = 0, 0, []
    def seek(self, offset, whence=0):
        self.position = offset + (self.position if whence == 1 else self.size if whence == 2 else 0)
        return self.position
    def tell(self): return self.position
    def write(self, data):
        self.parts.append((self.position, bytes(data)))
        self.position += len(data); self.size = max(self.size, self.position)
        return len(data)
    def flush(self): pass
    def get(self, start, end):
        result = bytearray(end - start + 1)
        for offset, data in self.parts:
            left, right = max(start, offset), min(end + 1, offset + len(data))
            if right > left: result[left - start:right - start] = data[left - offset:right - offset]
        return bytes(result)


def range_client(data):
    size = data.size if isinstance(data, SparseFile) else len(data)
    requests = []
    def handle(request):
        requests.append(request)
        start, end = map(int, re.fullmatch(r"bytes=(\d+)-(\d+)", request.headers["Range"]).groups())
        assert end - start < 1024 * 1024
        body = data.get(start, end) if isinstance(data, SparseFile) else data[start:end + 1]
        return httpx.Response(206, headers={"Content-Range": f"bytes {start}-{end}/{size}", "Content-Length": str(len(body)), "ETag": '"fixed"'}, content=body)
    return httpx.Client(transport=httpx.MockTransport(handle)), requests


@pytest.mark.parametrize("zip64", [False, True])
def test_zipfile_library_range_zip64_over_4gib(zip64):
    sparse = SparseFile()
    if zip64: sparse.seek((1 << 32) + 4096)
    with zipfile.ZipFile(sparse, "w", compression=zipfile.ZIP_DEFLATED) as z:
        with z.open("inside", "w", force_zip64=True) as out: out.write(b"range/zip64 acceptance")
    client, requests = range_client(sparse)
    with client, RangeReader("https://fixture.test/archive.zip", client=client, stop=threading.Event()) as reader:
        with zipfile.ZipFile(reader) as z: assert z.read("inside") == b"range/zip64 acceptance"
        assert reader.transferred_bytes < 200000
    assert requests


class ForbiddenBody(httpx.SyncByteStream):
    def __iter__(self): pytest.fail("invalid response body was consumed")
    def close(self): pass


@pytest.mark.parametrize("status,headers", [
    (200, {}), (416, {}), (302, {"Location": "https://other.test/archive.zip"}),
    (206, {"Content-Range": "bytes 0-0/10", "ETag": '"x"', "Content-Length": "1", "Content-Encoding": "gzip"}),
    (206, {"Content-Range": "bytes 1-1/10", "ETag": '"x"', "Content-Length": "1"}),
])
def test_range_200_never_reads_body(status, headers):
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(status, headers=headers, stream=ForbiddenBody())))
    with client, pytest.raises(ValueError): RangeReader("https://fixture.test/a", client=client, stop=threading.Event())


def test_etag_change_rejected_before_body():
    calls = []
    def handle(request):
        calls.append(request)
        if len(calls) == 1: return httpx.Response(206, headers={"Content-Range": "bytes 0-0/10", "ETag": '"x"', "Content-Length": "1"}, content=b"0")
        start, end = map(int, request.headers["Range"].removeprefix("bytes=").split("-"))
        return httpx.Response(206, headers={"Content-Range": f"bytes {start}-{end}/10", "ETag": '"changed"', "Content-Length": str(end - start + 1)}, stream=ForbiddenBody())
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with RangeReader("https://fixture.test/a", client=client, stop=threading.Event()) as reader:
            reader.seek(1)
            with pytest.raises(ValueError): reader.read(2)


def test_truncation_retries_and_byte_caps(monkeypatch):
    from musicsheet_transcription_eval import range_io
    calls = []
    def handle(request):
        start, end = map(int, request.headers["Range"].removeprefix("bytes=").split("-"))
        calls.append((start, end))
        body = b"0" if start == 0 and end == 0 else b"x"
        return httpx.Response(206, headers={"Content-Range": f"bytes {start}-{end}/100", "ETag": '"x"', "Content-Length": str(end - start + 1)}, content=body)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with RangeReader("https://fixture.test/a", client=client, stop=threading.Event()) as reader:
            reader.seek(1)
            with pytest.raises(ValueError): reader.read(2)
            assert len(calls) == 4  # initial probe + initial read + two retries
            assert reader.transferred_bytes == 4
    monkeypatch.setattr(range_io, "TRANSFER_LIMIT", 1)
    client, _ = range_client(b"12345")
    with client, RangeReader("https://fixture.test/a", client=client, stop=threading.Event()) as reader:
        reader.seek(1)
        with pytest.raises(ValueError): reader.read(1)


def test_seek_limits_and_cancellation():
    client, _ = range_client(b"12345")
    stop = threading.Event()
    with client, RangeReader("https://fixture.test/a", client=client, stop=stop) as reader:
        with pytest.raises(ValueError): reader.seek(-1)
        with pytest.raises(ValueError): reader.read(16 * 1024 * 1024 + 1)
        reader.seek(0); stop.set()
        with pytest.raises(InterruptedError): reader.read(1)


def test_sequential_zip_reads_use_bounded_one_mib_cache():
    client, requests = range_client(b"x" * (2 * 1024 * 1024))
    with client, RangeReader("https://fixture.test/a", client=client, stop=threading.Event()) as reader:
        for _ in range(32): assert reader.read(65536) == b"x" * 65536
        assert reader.transferred_bytes == 2 * 1024 * 1024 + 1
    assert len(requests) == 3


def test_central_directory_read_cap(monkeypatch):
    from musicsheet_transcription_eval import range_io
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as z:
        for i in range(20): z.writestr(str(i), b"x")
    client, _ = range_client(data.getvalue())
    with client, RangeReader("https://fixture.test/a", client=client, stop=threading.Event()) as reader:
        monkeypatch.setattr(range_io, "MAX_READ", 100)
        with pytest.raises(ValueError, match="read size limit"): zipfile.ZipFile(reader)
