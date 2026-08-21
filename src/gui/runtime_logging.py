"""Bounded, redacted file logging for the GUI process."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re


_AUTH_HEADER_PATTERN = re.compile(
    r"(?im)\b(authorization|proxy-authorization|cookie|set-cookie)\s*[:=]\s*[^\r\n]+"
)
_BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_QUERY_SECRET_PATTERN = re.compile(
    r"(?i)([?&](?:access[_-]?token|token|api[_-]?key|password|passwd|secret)=)[^&#\s]+"
)
_SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(authorization|password|passwd|token|cookie|secret|api[_-]?key|ltoken_v2)\b"
    r"\s*[:=]\s*(?!\[REDACTED\])(?:\"[^\"]*\"|'[^']*'|[^\s,;}\]]+)"
)
_HANDLER_MARKER = "_homework_helper_gui_rotating_handler"


def redact_sensitive_text(value: object) -> str:
    """Return diagnostic text with common credential forms removed."""
    text = str(value)
    text = _AUTH_HEADER_PATTERN.sub(lambda match: f"{match.group(1)}: [REDACTED]", text)
    text = _BEARER_PATTERN.sub("Bearer [REDACTED]", text)
    text = _QUERY_SECRET_PATTERN.sub(lambda match: f"{match.group(1)}[REDACTED]", text)
    return _SECRET_ASSIGNMENT_PATTERN.sub(
        lambda match: f"{match.group(1)}=[REDACTED]",
        text,
    )


class RedactingFormatter(logging.Formatter):
    """Redact the fully formatted record, including exception text."""

    def format(self, record: logging.LogRecord) -> str:
        return redact_sensitive_text(super().format(record))


def configure_gui_logging(
    app_data_dir: str | os.PathLike[str] | None = None,
    *,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
) -> Path:
    """Install one idempotent 10 MiB x 5 GUI log handler on the root logger."""
    if app_data_dir is None:
        from src.utils.app_paths import get_app_data_dir

        app_data_dir = get_app_data_dir()

    data_dir = Path(app_data_dir) / "homework_helper_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    log_path = data_dir / "gui.log"

    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        if getattr(handler, _HANDLER_MARKER, False):
            return Path(getattr(handler, "baseFilename", log_path))

    handler = RotatingFileHandler(
        log_path,
        maxBytes=max(1, int(max_bytes)),
        backupCount=max(1, int(backup_count)),
        encoding="utf-8",
        delay=True,
    )
    setattr(handler, _HANDLER_MARKER, True)
    handler.setLevel(logging.INFO)
    handler.setFormatter(
        RedactingFormatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root_logger.addHandler(handler)
    if root_logger.level == logging.NOTSET or root_logger.level > logging.INFO:
        root_logger.setLevel(logging.INFO)
    return log_path
