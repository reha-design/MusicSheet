"""Private stdlib launcher: acquire ownership before starting the actual tool."""
import base64
import json
import os
import signal
import subprocess
import sys
import time


def _available(stream):
    if os.name != "nt":
        try:
            return os.read(stream.fileno(), 65536)
        except BlockingIOError:
            return b""
    import ctypes as C
    import msvcrt
    kernel = C.WinDLL("kernel32", use_last_error=True)
    kernel.PeekNamedPipe.argtypes = [C.c_void_p, C.c_void_p, C.c_uint32,
        C.c_void_p, C.POINTER(C.c_uint32), C.c_void_p]
    kernel.PeekNamedPipe.restype = C.c_int
    count = C.c_uint32()
    handle = msvcrt.get_osfhandle(stream.fileno())
    if not kernel.PeekNamedPipe(handle, None, 0, None, C.byref(count), None):
        if C.get_last_error() == 109:  # Pipe closed by its writer.
            return b""
        raise OSError
    return os.read(stream.fileno(), min(65536, count.value)) if count.value else b""


def main():
    if os.name != "nt":
        # A caught signal is reset by exec; SIG_IGN would leak into the tool.
        signal.signal(signal.SIGTERM, lambda *_: None)
    sys.stdout.buffer.write(b"READY\n")
    sys.stdout.buffer.flush()
    if sys.stdin.buffer.read(1) != b"R":
        return 0
    captured = bytearray()
    overflow = launch_failed = False
    process = None
    capture = sys.argv[1] == "1"
    try:
        process = subprocess.Popen(sys.argv[2:], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, close_fds=True, bufsize=0)
        if capture and os.name != "nt":
            os.set_blocking(process.stdout.fileno(), False)

        def collect():
            nonlocal overflow
            data = _available(process.stdout)
            remaining = 4096 - len(captured)
            overflow = overflow or len(data) > remaining
            captured.extend(data[:remaining])
            return bool(data)

        while process.poll() is None:
            if capture:
                collect()
            time.sleep(.01)
        if capture:
            # Direct-tool completion, not inherited pipe EOF, ends collection.
            for _ in range(64):
                if not collect():
                    break
            process.stdout.close()
        code = process.wait()
    except Exception:
        code, launch_failed = 127, True
    frame = {"version": 1, "returncode": code, "stdout": base64.b64encode(captured).decode("ascii"),
        "overflow": overflow, "launch_failed": launch_failed}
    sys.stdout.write(json.dumps(frame) + "\n")
    sys.stdout.flush()
    sys.stdin.buffer.read(1)  # Keep the group leader until parent cleanup finishes.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
