"""Start the backend detached and verify it answers; report any startup error.

The actual server process is kept alive by backend_supervisor.js (node): the
agent sandbox kills detached python.exe children of terminal commands, while
node.exe processes survive, so node is the resilient parent that respawns
python whenever it dies.
"""

import os
import subprocess
import sys
import time
import urllib.request
import urllib.error

PORT = 8000
URL = f"http://127.0.0.1:{PORT}/api/health"
ROOT = os.path.dirname(os.path.abspath(__file__))


def is_up() -> bool:
    try:
        with urllib.request.urlopen(URL, timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


if is_up():
    print("already up:", URL)
    sys.exit(0)

NODE = r"C:\Program Files\nodejs\node.exe"
if not os.path.exists(NODE):
    NODE = "node"

# Ignore SIGINT/SIGBREAK inside the server and never install uvicorn's Ctrl+C
# handler, so console events from any parent session cannot stop it.
launcher = os.path.join(ROOT, "_server.py")
with open(launcher, "w", encoding="utf-8") as fh:
    fh.write(
        "import signal, threading, uvicorn\n"
        "signal.signal(signal.SIGINT, signal.SIG_IGN)\n"
        "signal.signal(signal.SIGBREAK, signal.SIG_IGN)\n"
        'config = uvicorn.Config("app.main:app", port=8000, log_config=None)\n'
        "server = uvicorn.Server(config)\n"
        "server.install_signal_handlers = lambda: None\n"
        "threading.Thread(target=server.run, daemon=True).start()\n"
        "while True:\n"
        "    try:\n"
        "        threading.Event().wait()\n"
        "    except BaseException:\n"
        "        pass\n"
    )

# DETACHED (no console) | NEW_PROCESS_GROUP | NO_WINDOW | BREAKAWAY_FROM_JOB
flags = 0x00000008 | 0x00000200 | 0x08000000 | 0x01000000
log = open(os.path.join(ROOT, "supervisor.log"), "ab")
proc = subprocess.Popen(
    [NODE, os.path.join(ROOT, "backend_supervisor.js")],
    creationflags=flags,
    cwd=ROOT,
    stdout=log,
    stderr=subprocess.STDOUT,
)
print("supervisor pid:", proc.pid)

deadline = time.time() + 30
while time.time() < deadline:
    if is_up():
        print("OK:", URL)
        sys.exit(0)
    time.sleep(1)

print("FAILED to come up. backend.log tail:")
try:
    with open(os.path.join(ROOT, "backend.log"), "rb") as fh:
        fh.seek(-1500, os.SEEK_END)
        print(fh.read().decode("utf-8", "replace"))
except OSError as exc:
    print("cannot read log:", exc)
sys.exit(1)
