"""Uvicorn launcher that ignores console signals (run via scheduled task).

Task Scheduler owns this process, but empirically it still receives
CTRL_C/CTRL_BREAK events when the invoking terminal session ends
(exit code 0xC000013A). Disabling uvicorn's handlers is not enough —
Python's own default SIGINT handler raises KeyboardInterrupt in the main
thread — so we ignore both signals at the C level.
"""

import os
import signal
import sys
import threading

# pythonw has no console: sys.stdout/stderr are None. Route them to the log.
_ROOT = os.path.dirname(os.path.abspath(__file__))
if sys.stdout is None:
    sys.stdout = open(os.path.join(_ROOT, "backend.log"), "ab", buffering=0)
if sys.stderr is None:
    sys.stderr = sys.stdout

signal.signal(signal.SIGINT, signal.SIG_IGN)
try:
    signal.signal(signal.SIGBREAK, signal.SIG_IGN)  # Windows CTRL_BREAK
except (AttributeError, ValueError):
    pass

import uvicorn

config = uvicorn.Config("app.main:app", port=8000, log_config=None)
server = uvicorn.Server(config)
server.install_signal_handlers = lambda: None
threading.Thread(target=server.run, daemon=True).start()
threading.Event().wait()  # sleep forever
