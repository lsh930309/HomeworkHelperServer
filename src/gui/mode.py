"""Runtime GUI mode resolution for HomeworkHelper.

The packaged executable is intentionally a single PyInstaller entrypoint.  The
installer/build step chooses which PyQt main-window implementation that
entrypoint should present by writing ``gui_mode.txt`` next to the executable.
Development and tests can override the mode with a CLI flag or environment
variable.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Sequence

GUI_MODE_V1 = "v1"
GUI_MODE_V2 = "v2"
GUI_MODE_FILE_NAME = "gui_mode.txt"
GUI_MODE_ENV = "HOMEWORKHELPER_GUI_VERSION"

_ALIASES = {
    "legacy": GUI_MODE_V1,
    "qt6": GUI_MODE_V1,
    "pyqt": GUI_MODE_V1,
    "old": GUI_MODE_V1,
    "1": GUI_MODE_V1,
    "v1": GUI_MODE_V1,
    "new": GUI_MODE_V2,
    "new_gui": GUI_MODE_V2,
    "main_gui": GUI_MODE_V2,
    "2": GUI_MODE_V2,
    "v2": GUI_MODE_V2,
}


def normalize_gui_mode(value: str | None, default: str = GUI_MODE_V1) -> str:
    """Return a supported GUI mode.

    Unknown values intentionally fall back to ``default`` so a malformed marker
    file never prevents the legacy-safe GUI from launching.
    """

    if value is None:
        return default
    key = str(value).strip().lower().replace("-", "_")
    return _ALIASES.get(key, default)


def _mode_from_argv(argv: Sequence[str]) -> str | None:
    for index, arg in enumerate(argv):
        if arg in {"--gui-version", "--gui-mode"} and index + 1 < len(argv):
            return normalize_gui_mode(argv[index + 1], default="")
        if arg.startswith("--gui-version="):
            return normalize_gui_mode(arg.split("=", 1)[1], default="")
        if arg.startswith("--gui-mode="):
            return normalize_gui_mode(arg.split("=", 1)[1], default="")
        if arg in {"--v1", "--legacy-gui"}:
            return GUI_MODE_V1
        if arg in {"--v2", "--new-gui"}:
            return GUI_MODE_V2
    return None


def _mode_file_for_executable(executable_path: str | os.PathLike[str]) -> Path:
    return Path(executable_path).resolve().with_name(GUI_MODE_FILE_NAME)


def resolve_gui_mode(
    argv: Sequence[str],
    env: Mapping[str, str] | None = None,
    executable_path: str | os.PathLike[str] | None = None,
    default: str = GUI_MODE_V1,
) -> str:
    """Resolve the GUI mode in precedence order.

    Precedence:
    1. CLI flag (developer/test override)
    2. ``HOMEWORKHELPER_GUI_VERSION`` environment variable
    3. packaged ``gui_mode.txt`` marker next to the executable
    4. safe default ``v1``
    """

    cli_mode = _mode_from_argv(argv)
    if cli_mode in {GUI_MODE_V1, GUI_MODE_V2}:
        return cli_mode

    env = env or os.environ
    env_mode = normalize_gui_mode(env.get(GUI_MODE_ENV), default="")
    if env_mode in {GUI_MODE_V1, GUI_MODE_V2}:
        return env_mode

    if executable_path:
        mode_file = _mode_file_for_executable(executable_path)
        try:
            if mode_file.exists():
                file_mode = normalize_gui_mode(mode_file.read_text(encoding="utf-8"), default="")
                if file_mode in {GUI_MODE_V1, GUI_MODE_V2}:
                    return file_mode
        except OSError:
            pass

    return normalize_gui_mode(default)

