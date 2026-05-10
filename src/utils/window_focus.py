"""Best-effort foreground focus helpers for launched games.

The actual foreground switch is Windows-only.  Other platforms return ``False``
so callers can keep a single scheduling path without platform branches in tests.
"""

from __future__ import annotations

import logging
import os
import sys

import psutil

logger = logging.getLogger(__name__)


def _normalize_path(path: str | None) -> str | None:
    if not path:
        return None
    try:
        return os.path.normcase(os.path.abspath(path))
    except Exception:
        return os.path.normcase(path)


def find_process_ids_by_executable(executable_path: str | None) -> list[int]:
    """Return running process IDs whose executable path matches ``executable_path``."""
    expected = _normalize_path(executable_path)
    if not expected:
        return []

    matches: list[int] = []
    for proc in psutil.process_iter(["pid", "exe"]):
        try:
            if _normalize_path(proc.info.get("exe")) == expected:
                matches.append(int(proc.info["pid"]))
        except (psutil.NoSuchProcess, psutil.AccessDenied, TypeError, FileNotFoundError):
            continue
    return matches


def _candidate_pids(pid: int | None, executable_path: str | None) -> list[int]:
    seen: set[int] = set()
    ordered: list[int] = []
    for value in ([pid] if pid else []) + find_process_ids_by_executable(executable_path):
        if value and value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def focus_process_window(
    *,
    pid: int | None = None,
    executable_path: str | None = None,
) -> bool:
    """Bring the first visible top-level window for a process to the foreground.

    Returns:
        ``True`` when a matching visible window was found and a foreground request
        was issued successfully.  Returns ``False`` while the process/window is
        still starting, on non-Windows platforms, or when Windows denies focus.
    """
    if sys.platform != "win32":
        return False

    pids = set(_candidate_pids(pid, executable_path))
    if not pids:
        return False

    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        hwnds: list[int] = []

        enum_proc_type = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows.argtypes = [enum_proc_type, wintypes.LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
        user32.AllowSetForegroundWindow.restype = wintypes.BOOL
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow.restype = wintypes.BOOL
        user32.BringWindowToTop.argtypes = [wintypes.HWND]
        user32.BringWindowToTop.restype = wintypes.BOOL
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL

        def _enum_proc(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            window_pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
            if int(window_pid.value) in pids:
                hwnds.append(int(hwnd))
                return False
            return True

        user32.EnumWindows(enum_proc_type(_enum_proc), 0)
        if not hwnds:
            return False

        hwnd = hwnds[0]
        try:
            user32.AllowSetForegroundWindow(0xFFFFFFFF)
        except Exception:
            logger.debug("AllowSetForegroundWindow failed", exc_info=True)

        SW_RESTORE = 9
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.BringWindowToTop(hwnd)
        return bool(user32.SetForegroundWindow(hwnd))
    except Exception:
        logger.debug("Failed to focus process window", exc_info=True)
        return False
