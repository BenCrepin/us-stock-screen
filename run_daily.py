"""
Daily job: refresh the universe, run the screen, write the dated archive.
Scheduled for 10:00 UK time via Windows Task Scheduler (see setup_schedule.ps1).

Usage:
    python run_daily.py                 # uses ./tickers.txt and ./archive
    python run_daily.py --no-refresh    # skip the constituent refresh
"""
import argparse
import io
import os
import subprocess
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
TICKERS = os.path.join(HERE, "tickers.txt")
ARCHIVE = os.path.join(HERE, "archive")
LOGS = os.path.join(HERE, "logs")

SOURCES = [  # Rule U1 to U3: S&P 500 + S&P 400 (all above the US$1bn floor)
    ("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", "Symbol"),
    ("https://en.wikipedia.org/wiki/List_of_S%26P_400_companies", "Symbol"),
]


def refresh_universe():
    import pandas as pd
    import requests
    ua = {"User-Agent": "Mozilla/5.0"}
    syms = []
    for url, col in SOURCES:
        html = requests.get(url, headers=ua, timeout=60).text
        table = next(t for t in pd.read_html(io.StringIO(html)) if col in t.columns)
        syms += table[col].astype(str).str.replace(".", "-", regex=False).tolist()
    syms = sorted(set(s for s in syms if s and s != "nan"))
    if len(syms) < 800:
        raise RuntimeError(f"constituent list looks incomplete ({len(syms)} symbols)")
    with open(TICKERS, "w") as fh:
        fh.write("\n".join(syms))
    return len(syms)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-refresh", action="store_true")
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()

    os.makedirs(LOGS, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    log_path = os.path.join(LOGS, f"run_{stamp}.log")
    with open(log_path, "w", encoding="utf-8") as log:
        def say(msg):
            print(msg, flush=True)
            log.write(msg + "\n"); log.flush()

        say(f"=== run_daily {datetime.now():%Y-%m-%d %H:%M:%S} ===")
        if a.no_refresh:
            say("universe refresh skipped")
        else:
            try:
                say(f"universe refreshed: {refresh_universe()} tickers")
            except Exception as e:  # noqa: BLE001
                say(f"WARNING universe refresh failed, reusing previous tickers.txt: {e}")
        if not os.path.exists(TICKERS):
            say("ERROR no tickers.txt available"); return 2

        cmd = [sys.executable, os.path.join(HERE, "screen.py"), "--tickers", TICKERS,
               "--archive", ARCHIVE, "--workers", str(a.workers)]
        say("running: " + " ".join(cmd))
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=HERE)
        log.write(proc.stdout); log.write(proc.stderr)
        tail = [l for l in proc.stdout.splitlines() if l.startswith(("archived", "wrote", "[")) and "PASS" in l or l.startswith("archived")]
        for l in tail:
            say(l)
        say(f"screen exit code {proc.returncode}")
        if proc.returncode == 0:
            publish_site(say)
        return proc.returncode


def publish_site(say):
    """Section 15: copy the latest page into docs/ and push it so GitHub Pages serves it.
    Does nothing (beyond the copy) until this folder is a git repo with an 'origin' remote."""
    import shutil
    latest = os.path.join(ARCHIVE, "latest")
    site = os.path.join(HERE, "docs")
    os.makedirs(site, exist_ok=True)
    pairs = [("report.html", "index.html"), ("qualifying.csv", "qualifying.csv"),
             ("monitoring.csv", "monitoring.csv"), ("report.md", "report.md")]
    for src, dst in pairs:
        s = os.path.join(latest, src)
        if os.path.exists(s):
            shutil.copyfile(s, os.path.join(site, dst))
    with open(os.path.join(site, ".nojekyll"), "w") as fh:
        fh.write("")
    if subprocess.run(["git", "-C", HERE, "remote", "get-url", "origin"], capture_output=True).returncode != 0:
        say("site publish skipped: no git remote configured (see SETUP_SITE.md)")
        return
    asof = ""
    try:
        with open(os.path.join(latest, "report.md"), encoding="utf-8") as fh:
            import re
            m = re.search(r"As of close: (\S+)", fh.read(400))
            asof = m.group(1) if m else ""
    except OSError:
        pass
    cmds = [["git", "-C", HERE, "add", "docs", "archive/INDEX.md", "archive/latest",
             "archive/" + asof if asof else "archive"],
            ["git", "-C", HERE, "commit", "-q", "-m", f"Screen as of {asof or 'latest'}"],
            ["git", "-C", HERE, "push", "-q"]]
    for c in cmds:
        r = subprocess.run(c, capture_output=True, text=True)
        if r.returncode != 0 and "nothing to commit" not in (r.stdout + r.stderr):
            say(f"WARNING git step failed ({' '.join(c[3:5])}): {(r.stderr or r.stdout).strip()[:300]}")
            return
    say("site published to GitHub Pages")


if __name__ == "__main__":
    sys.exit(main())
