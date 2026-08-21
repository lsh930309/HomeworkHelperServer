from __future__ import annotations

import logging
from pathlib import Path

from src.gui.runtime_logging import configure_gui_logging, redact_sensitive_text


def _remove_gui_handlers() -> None:
    root = logging.getLogger()
    for handler in tuple(root.handlers):
        if getattr(handler, "_homework_helper_gui_rotating_handler", False):
            root.removeHandler(handler)
            handler.close()


def test_redact_sensitive_text_covers_headers_queries_and_provider_tokens():
    text = (
        "Authorization: Bearer abc.def\nCookie=session=secret\n"
        "url=https://example.test/?access_token=query-secret\n"
        "token=generic-secret\nltoken_v2=hoyo-secret\npassword='pw'"
    )

    redacted = redact_sensitive_text(text)

    for secret in ("abc.def", "session=secret", "query-secret", "generic-secret", "hoyo-secret", "pw"):
        assert secret not in redacted
    assert redacted.count("[REDACTED]") >= 5


def test_configure_gui_logging_is_idempotent_and_rotates_with_redaction(tmp_path: Path):
    _remove_gui_handlers()
    root = logging.getLogger()
    original_level = root.level
    try:
        first = configure_gui_logging(tmp_path, max_bytes=220, backup_count=5)
        second = configure_gui_logging(tmp_path, max_bytes=220, backup_count=5)
        assert first == second
        assert sum(
            bool(getattr(handler, "_homework_helper_gui_rotating_handler", False))
            for handler in root.handlers
        ) == 1

        test_logger = logging.getLogger("tests.gui.runtime")
        for index in range(20):
            test_logger.info("entry=%s token=top-secret-%s", "x" * 40, index)
        for handler in root.handlers:
            if getattr(handler, "_homework_helper_gui_rotating_handler", False):
                handler.flush()

        files = sorted(first.parent.glob("gui.log*"))
        assert 2 <= len(files) <= 6
        combined = "\n".join(path.read_text(encoding="utf-8") for path in files)
        assert "top-secret" not in combined
        assert "token=[REDACTED]" in combined
    finally:
        _remove_gui_handlers()
        root.setLevel(original_level)


def test_gui_logging_starts_only_after_command_only_branches():
    source = Path("homework_helper.pyw").read_text(encoding="utf-8")

    shutdown_branch = source.index("shutdown_reason = _shutdown_request_reason()")
    server_branch = source.index("if _wants_server_only_mode():")
    logging_setup = source.index("gui_log_path = configure_gui_logging()")
    schema_migration = source.index("# === 스키마 자동 마이그레이션 ===")

    assert shutdown_branch < server_branch < logging_setup < schema_migration
