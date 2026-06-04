"""Runtime path and identity helpers shared by GUI, API server, and tests.

The normal desktop app stores user state under ``%APPDATA%/HomeworkHelper`` on
Windows (``~/.config/HomeworkHelper`` elsewhere).  The SSH real-device
testbench must be able to run next to a production host app without touching
that state, so this module centralises the environment overrides used for
isolated runs.
"""

from __future__ import annotations

import os
import re
from pathlib import Path


TEST_APPDATA_ENV = "HH_TEST_APPDATA_DIR"
TESTBENCH_SESSION_ENV = "HH_TESTBENCH_SESSION_ID"
SERVER_MUTEX_ENV = "HH_SERVER_MUTEX_NAME"
DEFAULT_APP_NAME = "HomeworkHelper"
DEFAULT_SERVER_MUTEX_NAME = r"Local\HomeworkHelperDBServerMutex"


def sanitize_runtime_token(value: str | None, *, fallback: str = "session") -> str:
    """Return a path/mutex safe short token for generated runtime identities."""
    raw = (value or "").strip()
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("._-")
    return (cleaned or fallback)[:64]


def get_testbench_session_id() -> str | None:
    """Return the current SSH testbench session id, if one is configured."""
    session_id = os.environ.get(TESTBENCH_SESSION_ENV)
    if not session_id:
        return None
    return sanitize_runtime_token(session_id)


def is_testbench_mode() -> bool:
    """Whether the current process should treat its state as disposable."""
    return bool(os.environ.get(TEST_APPDATA_ENV) or os.environ.get(TESTBENCH_SESSION_ENV))


def get_app_data_dir(app_name: str = DEFAULT_APP_NAME) -> str:
    """Return the application state directory and create it if needed.

    ``HH_TEST_APPDATA_DIR`` is intentionally interpreted as the final app state
    directory, not as a roaming-profile root.  This lets each remote test session
    use a unique disposable root such as ``%TEMP%\\HHHostTestbench\\...\\appdata``.
    """
    override = os.environ.get(TEST_APPDATA_ENV)
    if override:
        app_dir = Path(override).expanduser()
    else:
        if os.name == "nt":
            base = os.getenv("APPDATA") or os.path.expanduser("~")
        else:
            base = os.path.expanduser("~/.config")
        app_dir = Path(base) / app_name

    app_dir.mkdir(parents=True, exist_ok=True)
    return str(app_dir)


def get_server_mutex_name(default: str = DEFAULT_SERVER_MUTEX_NAME) -> str:
    """Return the Windows named mutex used to guard the API server process."""
    explicit = os.environ.get(SERVER_MUTEX_ENV)
    if explicit:
        return explicit
    session_id = get_testbench_session_id()
    if session_id:
        return f"{default}_{session_id}"
    return default
