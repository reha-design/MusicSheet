"""Bounded seek/read transport; ZIP/ZIP64 parsing belongs to stdlib zipfile."""

import io
import re
import threading
import time
from urllib.parse import urlsplit

import httpx
from musicsheet_pipeline.basic_pitch.io import check_stop

MAX_READ = 16 * 1024 * 1024
CHUNK = 1024 * 1024
TRANSFER_LIMIT = 6 * 1024 ** 3
ACQUISITION_SECONDS = 1800


class RangeReader(io.RawIOBase):
    def __init__(self, url: str, *, client: httpx.Client, stop: threading.Event):
        super().__init__()
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError("invalid HTTPS source")
        self.url, self.client, self.stop = url, client, stop
        self.deadline = time.monotonic() + ACQUISITION_SECONDS
        self.transferred_bytes, self.position = 0, 0
        self.archive_size, self.etag = None, None
        self._cache, self._cache_start = b"", 0
        self._fetch(0, 0)

    def _guard(self):
        if self.closed: raise ValueError("closed range reader")
        check_stop(self.stop)
        if time.monotonic() >= self.deadline: raise ValueError("acquisition time limit")

    def _fetch(self, start: int, end: int) -> bytes:
        self._guard()
        if self.transferred_bytes + end - start + 1 > TRANSFER_LIMIT: raise ValueError("transfer byte limit")
        for attempt in range(3):
            self._guard()
            request = self.client.build_request("GET", self.url,
                headers={"Range": f"bytes={start}-{end}", "Accept-Encoding": "identity"},
                timeout=min(60., self.deadline - time.monotonic()))
            for key in ("Authorization", "Proxy-Authorization", "Cookie"):
                request.headers.pop(key, None)
            try:
                response = self.client.send(request, auth=None, stream=True, follow_redirects=False)
                try:
                    match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
                    if response.status_code != 206 or response.headers.get("Content-Encoding", "identity").lower() != "identity" or match is None:
                        raise ValueError("range response headers rejected")
                    left, right, total = map(int, match.groups())
                    etag = response.headers.get("ETag", "")
                    if (left, right) != (start, end) or not right < total or not etag or etag.startswith("W/") or response.headers.get("Content-Length") != str(end - start + 1):
                        raise ValueError("range/length/object mismatch")
                    if self.archive_size is not None and (self.archive_size != total or self.etag != etag):
                        raise ValueError("archive object changed")
                    if self.archive_size is None: self.archive_size, self.etag = total, etag
                    result = bytearray()
                    for chunk in response.iter_bytes():
                        self._guard()
                        self.transferred_bytes += len(chunk)
                        if self.transferred_bytes > TRANSFER_LIMIT or len(result) + len(chunk) > end - start + 1:
                            raise ValueError("range transfer size limit")
                        result.extend(chunk)
                    if len(result) == end - start + 1: return bytes(result)
                finally:
                    response.close()
            except httpx.TransportError:
                if attempt == 2: raise ValueError("range transport unavailable") from None
            if attempt == 2: raise ValueError("truncated range after retries")
            if self.transferred_bytes + end - start + 1 > TRANSFER_LIMIT: raise ValueError("retry transfer limit")
        raise ValueError("range unavailable")

    def readable(self): return True
    def seekable(self): return True
    def tell(self): self._guard(); return self.position

    def seek(self, offset: int, whence: int = 0):
        self._guard()
        if type(offset) is not int or type(whence) is not int or whence not in {0, 1, 2}: raise ValueError("invalid seek")
        position = offset + (self.position if whence == 1 else self.archive_size if whence == 2 else 0)
        if not 0 <= position <= self.archive_size: raise ValueError("seek outside archive")
        self.position = position
        return position

    def read(self, size: int = -1):
        self._guard()
        if type(size) is not int or size < -1: raise ValueError("invalid read size")
        if size == -1: size = self.archive_size - self.position
        if size > MAX_READ: raise ValueError("read size limit")
        size = min(size, self.archive_size - self.position)
        result = bytearray()
        while size:
            if not self._cache_start <= self.position < self._cache_start + len(self._cache):
                self._cache_start = self.position
                length = min(CHUNK, self.archive_size - self.position)
                self._cache = self._fetch(self.position, self.position + length - 1)
            available = self._cache_start + len(self._cache) - self.position
            length = min(size, available)
            index = self.position - self._cache_start
            chunk = self._cache[index:index + length]
            self.position += length
            result.extend(chunk)
            size -= length
        return bytes(result)


class BoundedLocalReader(io.RawIOBase):
    """Apply the same central-directory/read cap to verified local archives."""
    def __init__(self, path, *, stop):
        self.source, self.stop = path.open("rb"), stop
    def readable(self): return True
    def seekable(self): return True
    def tell(self): return self.source.tell()
    def seek(self, offset, whence=0): check_stop(self.stop); return self.source.seek(offset, whence)
    def read(self, size=-1):
        check_stop(self.stop)
        if size < 0:
            position = self.source.tell()
            self.source.seek(0, 2); size = self.source.tell() - position; self.source.seek(position)
        if size > MAX_READ: raise ValueError("local ZIP read size limit")
        return self.source.read(size)
    def close(self):
        self.source.close()
        super().close()
