r"""Dev-only helper: capture a headless-Chrome screenshot of the live
subscription card, injecting the session token through localStorage.

Usage:
  .venv/Scripts/python.exe scripts/shot_plan_card.py <token> <out.png> [wait_seconds]

How it works:
  1. Writes a small injector page to frontend/public/__inj.html (a dev
     artefact; the caller deletes it afterwards). It runs same-origin JS
     that writes sfp_session + hoLastSection into localStorage and
     redirects to the dashboard.
  2. Boots the SPA signed-in via headless Chrome.
  3. Saves the full-height viewport to <out.png> after the virtual-time
     budget (the caller picks WIN_H tall enough to include the plan card).
"""
import pathlib
import subprocess
import sys

TOKEN = sys.argv[1] if len(sys.argv) > 1 else ""
OUT = sys.argv[2] if len(sys.argv) > 2 else "shot.png"
WAIT = int(sys.argv[3]) if len(sys.argv) > 3 else 14
WIN_H = int(sys.argv[4]) if len(sys.argv) > 4 else 2400

INJ = pathlib.Path("frontend/public/__inj.html")
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PROFILE = r"C:\Users\Lenovo\Downloads\New folder\.freebuff\chrome-profile"


def main() -> None:
    INJ.parent.mkdir(exist_ok=True)
    INJ.write_text(
        "<!doctype html><meta charset='utf-8'><script>"
        "localStorage.setItem('sfp_session','" + TOKEN + "');"
        "localStorage.setItem('hoLastSection','sec-ho-plan');"
        "location.replace('/#/');"
        "</script>",
        encoding="utf-8",
    )
    cmd = [
        CHROME,
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--disable-crash-reporter",
        "--user-data-dir=" + PROFILE,
        "--window-size=1400," + str(WIN_H),
        "--hide-scrollbars",
        f"--virtual-time-budget={WAIT * 1000}",
        f"--screenshot={OUT}",
        "http://localhost:5173/__inj.html",
    ]
    subprocess.run(cmd, timeout=WAIT + 60, check=False, capture_output=True)
    print("saved ->", OUT)


if __name__ == "__main__":
    main()
