"""Delivery pipeline for the Smart Financial Platform.

Stages:
  1. deps    - verify python venv + node_modules exist (fast no-op when ready)
  2. build   - TypeScript check of the frontend (npx tsc --noEmit)
  3. test    - pytest suite (engine, parsers, API)
  4. summary - PASS/FAIL verdict; exit code 0 only when everything passes

Usage:
    .venv/Scripts/python.exe scripts/deliver.py
    .venv/Scripts/python.exe scripts/deliver.py --skip-deps
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
NODE_DIR = Path("C:/Program Files/nodejs")
FRONTEND = ROOT / "frontend"

STEP = {"n": 0}


def sh(cmd: list[str], cwd: Path | None = None, timeout: int = 600, extra_path: Path | None = None) -> tuple[int, str]:
    env = os.environ.copy()
    if extra_path:
        env["PATH"] = f"{extra_path}{os.pathsep}{env.get('PATH', '')}"
    proc = subprocess.run(
        cmd, cwd=str(cwd or ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout, env=env,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def stage(name: str, cmd: list[str], cwd: Path | None = None, timeout: int = 600, extra_path: Path | None = None) -> bool:
    STEP["n"] += 1
    print(f"\n=== [{STEP['n']}] {name} ===")
    started = time.time()
    try:
        code, output = sh(cmd, cwd=cwd, timeout=timeout, extra_path=extra_path)
    except subprocess.TimeoutExpired:
        print(f"TIMEOUT after {timeout}s")
        return False
    tail = output.strip().splitlines()
    if tail:
        print("\n".join(tail[-15:]))
    ok = code == 0
    print(f"{'PASS' if ok else 'FAIL'} ({time.time() - started:.1f}s)")
    return ok


def main() -> int:
    args = set(sys.argv[1:])
    results: dict[str, bool] = {}

    # -- stage 1: dependencies present?
    if "--skip-deps" not in args:
        deps_ok = VENV_PY.exists() and (FRONTEND / "node_modules").exists()
        print("=== [1] deps check ===")
        print(f"venv python : {'OK' if VENV_PY.exists() else 'MISSING'}")
        print(f"node_modules: {'OK' if (FRONTEND / 'node_modules').exists() else 'MISSING'}")
        print("PASS" if deps_ok else "FAIL (run: pip install -r requirements.txt && cd frontend && npm install)")
        results["deps"] = deps_ok
        if not deps_ok:
            return _summary({"deps": False})
    else:
        print("(deps stage skipped)")

    # -- stage 2: frontend type check
    tsc_cmd = [str(NODE_DIR / "npx.cmd"), "tsc", "--noEmit"] if NODE_DIR.exists() else ["npx", "tsc", "--noEmit"]
    results["build"] = stage(
        "build: typescript check (frontend)",
        tsc_cmd, cwd=FRONTEND, timeout=300, extra_path=NODE_DIR if NODE_DIR.exists() else None,
    )

    # -- stage 3: pytest suite
    py = str(VENV_PY) if VENV_PY.exists() else sys.executable
    results["test"] = stage(
        "test: pytest suite (engine + parsers + API)",
        [py, "-m", "pytest", "tests", "-q", "--tb=short"],
        cwd=ROOT, timeout=900,
    )

    return _summary(results)


def _summary(results: dict[str, bool]) -> int:
    print("\n" + "=" * 46)
    print("DELIVERY SUMMARY")
    for name, ok in results.items():
        print(f"  {name:8} : {'PASS' if ok else 'FAIL'}")
    verdict = "ALL GREEN - ready to deliver" if all(results.values()) else "FAILURES - not ready"
    print("=" * 46)
    print(verdict)
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
