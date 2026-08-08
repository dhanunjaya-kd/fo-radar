#!/usr/bin/env python3
"""
Auto-sync F&O Radar -> GitHub.

Watches the whole project folder. On any change, waits a short quiet
window (a few seconds) for rapid-fire saves to settle -- an editor
writing several files back to back, or the scanner logging a new
signal to Excel -- then commits everything and pushes to GitHub in
one shot.

This does NOT re-implement .gitignore -- it just runs `git add -A`,
which already respects it. Anything excluded there (.env, venv/,
node_modules/, the Fyers token file) is never staged, never committed,
regardless of how this script runs.

SETUP (one-time, do this BEFORE running this script):
    1. Finish the manual GitHub steps first -- git init, .gitignore in
       place, first commit, git remote add origin ..., first
       `git push -u origin main`. This script assumes the remote and
       your GitHub credentials are already working.
    2. pip install watchdog

RUNNING IT:
    From the project root: python auto_sync.py
    Leave that terminal window open while you work -- it prints a
    line each time it pushes. Ctrl+C to stop.

Expect a commit roughly every time something actually changes on
disk -- for signal_logs specifically, that's roughly every time a new
signal gets logged or an SL/target outcome updates, not on some fixed
timer, so it won't fire every single minute regardless of activity.
"""

import subprocess
import time
from pathlib import Path

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
except ImportError:
    print("Missing dependency. Run: pip install watchdog")
    raise SystemExit(1)

PROJECT_ROOT = Path(__file__).resolve().parent
DEBOUNCE_SECONDS = 4  # quiet time after the last change before committing

# Skip reacting to changes inside these -- git's own bookkeeping, or
# folders .gitignore already excludes anyway. This just avoids waking
# up and re-checking git status for noise we know won't be committed;
# .gitignore is still the actual source of truth for what gets staged.
IGNORE_DIR_NAMES = {".git", "node_modules", "venv", "__pycache__", ".vite"}


class ChangeHandler(FileSystemEventHandler):
    def __init__(self):
        self.pending = False
        self.last_event_time = 0.0

    def _relevant(self, path_str):
        parts = Path(path_str).parts
        return not any(p in IGNORE_DIR_NAMES for p in parts)

    def on_any_event(self, event):
        if event.is_directory:
            return
        if not self._relevant(event.src_path):
            return
        self.pending = True
        self.last_event_time = time.time()


def run_git(*args):
    return subprocess.run(
        ["git", *args], cwd=PROJECT_ROOT,
        capture_output=True, text=True
    )


def sync_once():
    add = run_git("add", "-A")
    if add.returncode != 0:
        print(f"[auto-sync] git add failed: {add.stderr.strip()}")
        return

    status = run_git("status", "--porcelain")
    if not status.stdout.strip():
        return  # nothing actually changed once .gitignore is applied

    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    commit = run_git("commit", "-m", f"Auto-sync {timestamp}")
    if commit.returncode != 0:
        print(f"[auto-sync] git commit failed: {commit.stderr.strip()}")
        return

    push = run_git("push")
    if push.returncode != 0:
        print(f"[auto-sync] git push failed, will retry on next change: {push.stderr.strip()}")
        print("[auto-sync] (commit is saved locally either way -- nothing is lost)")
        return

    print(f"[auto-sync] pushed at {timestamp}")


def main():
    handler = ChangeHandler()
    observer = Observer()
    observer.schedule(handler, str(PROJECT_ROOT), recursive=True)
    observer.start()
    print(f"[auto-sync] watching {PROJECT_ROOT}")
    print("[auto-sync] Ctrl+C to stop")

    try:
        while True:
            time.sleep(1)
            if handler.pending and (time.time() - handler.last_event_time) >= DEBOUNCE_SECONDS:
                handler.pending = False
                sync_once()
    except KeyboardInterrupt:
        print("\n[auto-sync] stopped")
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
