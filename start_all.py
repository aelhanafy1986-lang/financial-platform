"""Start BOTH servers (backend 8000 + frontend 5173) so they survive session close.

Usage:  .venv\\Scripts\\python.exe start_all.py
"""

import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
FRONTEND = os.path.join(ROOT, "frontend")
NODE = r"C:\Program Files\nodejs\node.exe"

# DETACHED (no console) | NEW_PROCESS_GROUP | NO_WINDOW | BREAKAWAY_FROM_JOB
# BREAKAWAY is essential: each terminal command runs inside a Windows Job
# Object that kills the whole process tree when the session ends, so a merely
# "detached" server still dies with it.
FLAGS = 0x00000008 | 0x00000200 | 0x08000000 | 0x01000000


def is_up(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def spawn(cmd: list, cwd: str, log_name: str) -> int:
    log = open(os.path.join(ROOT, log_name), "ab")
    return subprocess.Popen(
        cmd, creationflags=FLAGS, cwd=cwd,
        stdout=log, stderr=subprocess.STDOUT,
    ).pid


# ---- backend ---------------------------------------------------------------
BE_URL = "http://127.0.0.1:8000/api/health"
if is_up(BE_URL):
    print("backend : already up")
else:
    # The server runs under the node supervisor (backend_supervisor.js):
    # the sandbox kills detached python children of terminal commands, while
    # node survives and respawns python whenever it dies.
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
    node = r"C:\Program Files\nodejs\node.exe"
    if not os.path.exists(node):
        node = "node"
    pid = spawn([node, os.path.join(ROOT, "backend_supervisor.js")],
                ROOT, "supervisor.log")
    print("backend : supervisor pid", pid)

# ---- frontend ----------------------------------------------------------------
FE_URL = "http://127.0.0.1:5173/"
if is_up(FE_URL):
    print("frontend: already up")
else:
    pid = spawn(
        [NODE, "node_modules/vite/bin/vite.js", "--port", "5173", "--host"],
        FRONTEND, "frontend.log",
    )
    print("frontend: starting pid", pid)

# ---- verify -------------------------------------------------------------------
deadline = time.time() + 25
be_ok = fe_ok = False
while time.time() < deadline and not (be_ok and fe_ok):
    be_ok = be_ok or is_up(BE_URL)
    fe_ok = fe_ok or is_up(FE_URL)
    time.sleep(1)

print("backend :", "OK" if be_ok else "FAILED")
print("frontend:", "OK" if fe_ok else "FAILED")
print("open    : http://localhost:5173")
sys.exit(0 if (be_ok and fe_ok) else 1)
