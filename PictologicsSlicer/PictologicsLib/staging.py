"""Process-marker helpers for privacy-sensitive temporary job directories."""

from __future__ import annotations

import os
from pathlib import Path


def read_pid_marker(marker: str | os.PathLike[str]) -> int | None:
    """Read the extension's ``pid=N`` marker format, returning ``None`` if invalid."""

    try:
        text = Path(marker).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None
    if not text.startswith("pid="):
        return None
    try:
        pid = int(text.removeprefix("pid="))
    except ValueError:
        return None
    return pid if 0 < pid <= 0xFFFFFFFF else None


def process_is_alive(pid: int) -> bool:
    """Return whether *pid* is live without signalling or modifying it.

    Liveness is PID-based only: after a crash whose PID has been recycled by an
    unrelated process this returns True, so the abandoned staging directory is
    retained rather than reclaimed. That is the intentionally safe direction (never
    delete a directory a live process may be using); the ``purgeStaleJobs`` age gates
    eventually reclaim it. A stronger design would pair the PID with process start
    time, which needs platform-specific queries and is out of scope here.
    """

    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":  # pragma: no cover - Windows-only OpenProcess path; POSIX CI cannot execute it
        try:
            import ctypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
            kernel32.OpenProcess.restype = ctypes.c_void_p
            handle = kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                # Access denied is conservative evidence that a process exists.
                return ctypes.get_last_error() == 5  # type: ignore[attr-defined,no-any-return]
            try:
                exit_code = ctypes.c_ulong()
                if not kernel32.GetExitCodeProcess(
                    ctypes.c_void_p(handle), ctypes.byref(exit_code)
                ):
                    return True
                return exit_code.value == 259  # STILL_ACTIVE
            finally:
                kernel32.CloseHandle(ctypes.c_void_p(handle))
        except (AttributeError, OSError, OverflowError, ValueError):
            return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, OverflowError):
        return False
    return True
