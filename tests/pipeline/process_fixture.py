"""Standalone, bounded child processes for lifecycle tests."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


mode, root = sys.argv[1], Path(sys.argv[2])
root.mkdir(parents=True, exist_ok=True)
if mode == "echo":
    print(json.dumps(sys.argv[3:]))
elif mode == "env":
    print(os.environ.get("DATABASE_URL", "absent"))
elif mode == "overflow":
    sys.stdout.write("x" * 100_000)
elif mode == "child":
    if os.name != "nt":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    (root / "child.pid").write_text(str(os.getpid()))
    time.sleep(25)
elif mode in {"wait", "linger"}:
    subprocess.Popen([sys.executable, __file__, "child", str(root)])
    (root / "parent.pid").write_text(str(os.getpid()))
    deadline = time.monotonic() + 5
    while not (root / "child.pid").exists() and time.monotonic() < deadline:
        time.sleep(.01)
    (root / "ready").touch()
    if mode == "wait":
        time.sleep(25)
    else:
        print("done", flush=True)
else:
    raise SystemExit(2)
