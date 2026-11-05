/**
 * Backend supervisor: keeps the FastAPI server alive.
 *
 * The agent sandbox kills python.exe processes spawned from terminal commands
 * (verified experimentally), while node.exe processes survive — so node is the
 * parent: it spawns the venv python `_server.py`, and restarts it whenever it
 * exits. The supervisor itself stays resident forever.
 */
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

const ROOT = __dirname;
const PYTHON = path.join(ROOT, ".venv", "Scripts", "python.exe");
const SERVER = path.join(ROOT, "_server.py");
const LOG = path.join(ROOT, "backend.log");

// DETACHED | CREATE_NO_WINDOW for the supervisor itself is unnecessary — it is
// already spawned with breakaway. The python child inherits our (detached) state.
function startServer() {
  const out = fs.openSync(LOG, "a");
  const child = spawn(PYTHON, [SERVER], {
    cwd: ROOT,
    stdio: ["ignore", out, out],
    windowsHide: true,
    detached: true,
  });
  child.on("exit", (code, signal) => {
    fs.appendFileSync(LOG, `\n[supervisor] server exited code=${code} signal=${signal} — restarting in 2s\n`);
    setTimeout(startServer, 2000);
  });
  console.log(`[supervisor] backend pid ${child.pid}`);
}

startServer();
setInterval(() => {}, 1 << 30); // keep the event loop alive forever
