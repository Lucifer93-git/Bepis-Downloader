"""Windows self-update helper for BepisDB Downloader.

This program is packaged as BepisDB-Updater.exe. The main GUI launches it after
downloading/extracting a newer release. It waits for the main EXE to exit,
replaces installed files while preserving config.ini, then relaunches the app.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def wait_for_pid(pid: int, timeout: int = 60) -> None:
    """Wait until the old GUI process exits before replacing its files."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(0.5)
    raise RuntimeError("The old BepisDB Downloader process did not close in time.")


def copy_update(source: Path, target: Path) -> None:
    """Copy the extracted release into the install folder, preserving config.ini."""
    preserved = {"config.ini"}

    for item in source.iterdir():
        if item.name.casefold() in preserved:
            continue

        destination = target / item.name

        if item.is_dir():
            if destination.exists():
                shutil.rmtree(destination, ignore_errors=True)
            shutil.copytree(item, destination)
        else:
            # Retry briefly in case Windows still has a file handle open.
            last_error = None
            for _ in range(20):
                try:
                    shutil.copy2(item, destination)
                    last_error = None
                    break
                except OSError as exc:
                    last_error = exc
                    time.sleep(0.5)
            if last_error is not None:
                raise last_error


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--pid", required=True, type=int)
    parser.add_argument("--launch", default="BepisDB-Downloader.exe")
    args = parser.parse_args()

    source = Path(args.source).resolve()
    target = Path(args.target).resolve()

    if not source.exists():
        return 2

    target.mkdir(parents=True, exist_ok=True)

    try:
        wait_for_pid(args.pid)
        copy_update(source, target)

        launch = target / args.launch
        if launch.exists():
            subprocess.Popen(
                [str(launch)],
                cwd=str(target),
                creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
        return 0
    finally:
        # The extracted update lives in a temp directory and is safe to remove.
        try:
            shutil.rmtree(source.parent, ignore_errors=True)
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
