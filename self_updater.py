"""Windows self-update helper for BepisDB Downloader.

Packaged as BepisDB-Updater.exe. It waits for the old GUI process to really
exit, stages new files, replaces them with lock-aware retries, preserves
config.ini, and relaunches the downloader.
"""
from __future__ import annotations

import argparse
import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


PRESERVED_NAMES = {"config.ini"}
REPLACE_TIMEOUT_SECONDS = 120
RETRY_INTERVAL_SECONDS = 0.75


def _wait_for_process_windows(pid: int, timeout: int = 90) -> bool:
    """Wait for one exact Windows PID using a process handle."""
    PROCESS_SYNCHRONIZE = 0x00100000
    WAIT_OBJECT_0 = 0x00000000
    WAIT_TIMEOUT = 0x00000102

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_SYNCHRONIZE, False, pid)
    if not handle:
        # Process already disappeared or cannot be opened.
        return True

    try:
        result = kernel32.WaitForSingleObject(handle, int(timeout * 1000))
        return result == WAIT_OBJECT_0
    finally:
        kernel32.CloseHandle(handle)


def wait_for_pid(pid: int, timeout: int = 90) -> None:
    """Wait until the old GUI process has actually terminated."""
    if sys.platform.startswith("win"):
        if _wait_for_process_windows(pid, timeout):
            # Small grace period for Windows/AV to release image handles.
            time.sleep(2.0)
            return
        raise RuntimeError("The old BepisDB Downloader process did not close in time.")

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            time.sleep(1.0)
            return
        time.sleep(0.5)
    raise RuntimeError("The old BepisDB Downloader process did not close in time.")


def _retry(action, description: str, timeout: int = REPLACE_TIMEOUT_SECONDS) -> None:
    """Retry a Windows file operation while another process still holds a lock."""
    deadline = time.time() + timeout
    last_error = None

    while time.time() < deadline:
        try:
            action()
            return
        except (PermissionError, OSError) as exc:
            last_error = exc
            time.sleep(RETRY_INTERVAL_SECONDS)

    raise RuntimeError(
        f"Could not replace {description} after {timeout} seconds. "
        f"Windows is still using the file. Last error: {last_error}"
    )


def _copy_file_staged(source: Path, destination: Path) -> None:
    """Copy beside the destination first, then atomically replace it."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    staged = destination.with_name(destination.name + ".bepis-new")

    try:
        if staged.exists():
            staged.unlink()
    except OSError:
        pass

    shutil.copy2(source, staged)

    def replace():
        os.replace(staged, destination)

    try:
        _retry(replace, str(destination))
    finally:
        try:
            if staged.exists():
                staged.unlink()
        except OSError:
            pass


def _replace_directory(source: Path, destination: Path) -> None:
    """Merge a directory recursively so one locked file does not nuke the tree."""
    destination.mkdir(parents=True, exist_ok=True)

    source_names = set()
    for child in source.iterdir():
        source_names.add(child.name.casefold())
        target_child = destination / child.name
        if child.is_dir():
            _replace_directory(child, target_child)
        else:
            _copy_file_staged(child, target_child)

    # Remove stale files/directories left from the previous onedir build.
    # Retry removals because antivirus/Explorer can briefly retain handles.
    for old in list(destination.iterdir()):
        if old.name.casefold() in source_names:
            continue
        if old.name.casefold() in PRESERVED_NAMES:
            continue

        if old.is_dir():
            def remove_dir(path=old):
                shutil.rmtree(path)
            try:
                _retry(remove_dir, str(old), timeout=45)
            except Exception:
                # Stale leftovers are harmless; the new build has already been
                # merged. Do not fail an otherwise valid update for cleanup.
                pass
        else:
            def remove_file(path=old):
                path.unlink()
            try:
                _retry(remove_file, str(old), timeout=45)
            except Exception:
                pass


def copy_update(source: Path, target: Path) -> None:
    """Install extracted files while preserving user configuration."""
    for item in source.iterdir():
        if item.name.casefold() in PRESERVED_NAMES:
            continue

        destination = target / item.name
        if item.is_dir():
            _replace_directory(item, destination)
        else:
            _copy_file_staged(item, destination)


def _show_error(message: str) -> None:
    """Show a readable Windows error without exposing a PyInstaller traceback."""
    if sys.platform.startswith("win"):
        try:
            ctypes.windll.user32.MessageBoxW(
                0,
                message,
                "BepisDB Update Failed",
                0x10,
            )
            return
        except Exception:
            pass
    print(message, file=sys.stderr)


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
        _show_error("The downloaded update files could not be found.")
        return 2

    target.mkdir(parents=True, exist_ok=True)

    try:
        wait_for_pid(args.pid)
        copy_update(source, target)

        launch = target / args.launch
        if not launch.exists():
            raise RuntimeError(
                f"Update files were installed, but {args.launch} was not found."
            )

        subprocess.Popen(
            [str(launch)],
            cwd=str(target),
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            close_fds=True,
        )
        return 0

    except Exception as exc:
        _show_error(
            "The automatic update could not finish.\n\n"
            f"{exc}\n\n"
            "Your existing config.ini was preserved. "
            "Close the downloader and try the update again."
        )
        return 1

    finally:
        # The extracted package lives in a temporary update directory.
        try:
            shutil.rmtree(source.parent, ignore_errors=True)
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
