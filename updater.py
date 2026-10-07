"""Automatic updater / launcher for BepisDB Downloader.

Original project:
    BepisDB-downloader by 0AwsD0
    https://github.com/0AwsD0/BepisDB-downloader

Updated version by:
    LuC!f3r

Run this file instead of main.py. It checks the public GitHub repository for a
new version, offers to update program files, preserves config.ini, then starts
the downloader.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path


REPOSITORY = "Lucifer93-git/Bepis-Downloader"
BRANCH = "main"
RAW_BASE = f"https://raw.githubusercontent.com/{REPOSITORY}/{BRANCH}"

VERSION_FILE = "version.txt"

# config.ini is intentionally NOT in this list. User settings must survive
# updates. updater.py is included so the updater itself can also improve later.
UPDATE_FILES = [
    "main.py",
    "download.py",
    "requirements.txt",
    "README.md",
    "updater.py",
    VERSION_FILE,
]

REQUEST_TIMEOUT = 20
USER_AGENT = "BepisDB-Downloader-Updater/1.0"


def _local_path(name: str) -> Path:
    return Path(__file__).resolve().parent / name


def _read_local_version() -> str:
    path = _local_path(VERSION_FILE)
    try:
        value = path.read_text(encoding="utf-8").strip()
        return value or "unknown"
    except OSError:
        return "unknown"


def _download_bytes(name: str) -> bytes:
    url = f"{RAW_BASE}/{name}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        return response.read()


def _remote_version() -> str:
    return _download_bytes(VERSION_FILE).decode("utf-8").strip()


def _start_downloader() -> int:
    main_file = _local_path("gui.py") if _local_path("gui.py").exists() else _local_path("main.py")
    if not main_file.exists():
        print("\nThe downloader entry point was not found. Please restore the program files.")
        return 1

    print("\nStarting BepisDB Downloader...\n")
    try:
        return subprocess.call([sys.executable, str(main_file)], cwd=str(main_file.parent))
    except OSError as exc:
        print(f"Could not start the downloader: {exc}")
        return 1


def _ask_update(current: str, latest: str) -> str:
    print(f"Current version: {current}")
    print(f"Latest version:  {latest}")
    print("\nUpdate available.\n")
    print("1. Update now")
    print("2. Skip this update")
    print("3. Exit")

    while True:
        choice = input("\n> ").strip()
        if choice in {"1", "2", "3"}:
            return choice
        print("\nPlease select 1, 2, or 3.")


def _install_requirements_if_changed(changed: bool) -> None:
    if not changed:
        return

    requirements = _local_path("requirements.txt")
    if not requirements.exists():
        return

    print("\nPython requirements changed.")
    print("Updating requirements...")

    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(requirements)],
        cwd=str(requirements.parent),
    )

    if result.returncode != 0:
        print("\nWARNING: Requirements could not be updated automatically.")
        print("You can run this manually later:")
        print("python -m pip install -r requirements.txt")
    else:
        print("Requirements updated.")


def _apply_update(latest: str) -> bool:
    root = Path(__file__).resolve().parent
    stage_dir = Path(tempfile.mkdtemp(prefix="bepis_update_", dir=str(root)))
    backup_dir = stage_dir / "backup"
    backup_dir.mkdir(parents=True, exist_ok=True)

    requirements_before = None
    req_path = root / "requirements.txt"
    if req_path.exists():
        try:
            requirements_before = req_path.read_bytes()
        except OSError:
            pass

    print("\nDownloading update...")

    try:
        # Download the entire update before replacing any installed file.
        for name in UPDATE_FILES:
            data = _download_bytes(name)
            (stage_dir / name).write_bytes(data)

        # Sanity-check the staged version before touching the installed copy.
        staged_version = (stage_dir / VERSION_FILE).read_text(encoding="utf-8").strip()
        if staged_version != latest:
            raise RuntimeError(
                f"Version changed while updating ({latest} -> {staged_version}). "
                "Please run the updater again."
            )

        replaced = []

        try:
            # Replace updater.py last so this running process keeps the simplest
            # possible self-update path.
            order = [name for name in UPDATE_FILES if name != "updater.py"] + ["updater.py"]

            for name in order:
                target = root / name
                staged = stage_dir / name
                backup = backup_dir / name

                if target.exists():
                    shutil.copy2(target, backup)

                os.replace(staged, target)
                replaced.append(name)

        except Exception:
            # Roll back files already replaced if anything fails.
            for name in reversed(replaced):
                target = root / name
                backup = backup_dir / name
                try:
                    if backup.exists():
                        os.replace(backup, target)
                    elif target.exists():
                        target.unlink()
                except OSError:
                    pass
            raise

        requirements_after = None
        if req_path.exists():
            try:
                requirements_after = req_path.read_bytes()
            except OSError:
                pass

        print(f"Update complete: {latest}")
        _install_requirements_if_changed(requirements_before != requirements_after)
        return True

    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        print(f"\nUpdate download failed: {exc}")
        print("Your installed files were left unchanged.")
        return False
    except Exception as exc:
        print(f"\nUpdate failed: {exc}")
        print("Your previous files were restored where possible.")
        return False
    finally:
        shutil.rmtree(stage_dir, ignore_errors=True)


def main() -> int:
    print("BepisDB Downloader")
    print("------------------")
    print("Checking for updates...\n")

    current = _read_local_version()

    try:
        latest = _remote_version()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, UnicodeError) as exc:
        print(f"Could not check for updates: {exc}")
        print("Starting the installed version instead.")
        return _start_downloader()

    if not latest:
        print("GitHub returned an empty version value.")
        print("Starting the installed version instead.")
        return _start_downloader()

    if current == latest:
        print(f"Already up to date: {current}")
        return _start_downloader()

    choice = _ask_update(current, latest)

    if choice == "3":
        return 0

    if choice == "1":
        _apply_update(latest)

    # Whether the user skipped or an update failed, start whatever valid
    # installed version is currently present.
    return _start_downloader()


if __name__ == "__main__":
    raise SystemExit(main())
