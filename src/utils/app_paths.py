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


class CapturePathError(ValueError):
    """A capture destination cannot be used safely."""


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


def _app_data_path(app_name: str) -> Path:
    # A test override is the final app directory, not a roaming-profile root.
    override = os.environ.get(TEST_APPDATA_ENV)
    if override:
        return Path(override).expanduser()
    base = (os.getenv("APPDATA") or os.path.expanduser("~")) if os.name == "nt" else os.path.expanduser("~/.config")
    return Path(base) / app_name


def get_app_data_dir(app_name: str = DEFAULT_APP_NAME) -> str:
    """Return the application state directory and create it if needed."""
    app_dir = _app_data_path(app_name)
    app_dir.mkdir(parents=True, exist_ok=True)
    return str(app_dir)


def validate_capture_output_path(path: str | Path) -> Path:
    """Resolve a capture destination outside the host data tree, without creating it."""
    try:
        target = Path(path).expanduser()
        app_data = _app_data_path(DEFAULT_APP_NAME)
        resolved = Path(os.path.realpath(target, strict=os.path.ALLOW_MISSING))
        resolved_data = Path(os.path.realpath(app_data, strict=os.path.ALLOW_MISSING))
        declared_in_data = Path(os.path.abspath(target)).is_relative_to(Path(os.path.abspath(app_data)))
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        raise CapturePathError("캡처 저장 경로를 확인할 수 없습니다. 접근 가능한 다른 폴더를 선택해 주세요.") from error
    if declared_in_data or resolved.is_relative_to(resolved_data):
        raise CapturePathError("호스트 앱 데이터 폴더에는 스크린샷이나 녹화를 저장할 수 없습니다. 다른 폴더를 선택해 주세요.")
    return resolved


def get_server_mutex_name(default: str = DEFAULT_SERVER_MUTEX_NAME) -> str:
    """Return the Windows named mutex used to guard the API server process."""
    explicit = os.environ.get(SERVER_MUTEX_ENV)
    if explicit:
        return explicit
    session_id = get_testbench_session_id()
    if session_id:
        return f"{default}_{session_id}"
    return default
