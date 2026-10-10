"""Exercise fault startup and recovery without opening normal DB consumers."""
import ast
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from src.api.runtime_config import gui_health_url, resolve_local_api_base_url
from src.gui.beholder_dialog import BeholderBackupRestoreDialog


def _startup_functions():
    source = Path("homework_helper.pyw").read_text(encoding="utf-8")
    names = {
        "_server_health_payload", "_is_existing_server_alive", "wait_for_server_ready",
        "_prepare_gui_database",
    }
    definitions = [
        node for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    namespace = {
        "Any": Any, "SingleInstanceApplication": object,
        "gui_health_url": gui_health_url,
        "resolve_local_api_base_url": resolve_local_api_base_url,
        "time": SimpleNamespace(sleep=lambda _seconds: None),
        "QMessageBox": QMessageBox,
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=definitions, type_ignores=[])),
                 "homework_helper.pyw", "exec"), namespace)
    return namespace


def _wait_restore(dialog):
    app = QApplication.instance() or QApplication([])
    deadline = time.monotonic() + 3.0
    while dialog._request_worker is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.002)
    assert dialog._request_worker is None


@pytest.fixture
def recovery_server():
    calls = []
    outcome = {"restore_status": 200, "preview_status": 200}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            calls.append(("GET", self.path))
            if self.path == "/api/gui/ping":
                self._reply({"ok": True})
            elif self.path == "/api/gui/health":
                self._reply({"ok": False, "db_ready": False, "db_error": "database_faulted",
                             "database_access": {"mode": "faulted"}})
            elif self.path == "/api/beholder/backups":
                self._reply({"backups": [{"slot": 1, "modified_at": 0, "size": 4096,
                                          "user_summary": "정상 백업"}]})
            else:
                self._reply({"detail": "normal DB access is forbidden"}, 503)

        def do_POST(self):
            calls.append(("POST", self.path))
            length = int(self.headers.get("Content-Length", "0"))
            assert json.loads(self.rfile.read(length)) == {"slot": 1}
            if self.path.endswith("restore-preview"):
                self._reply({"impact": {"summary": "기존 데이터 보존 후 백업을 적용합니다."}},
                            outcome["preview_status"])
            else:
                self._reply({"ok": outcome["restore_status"] == 200}, outcome["restore_status"])

        def _reply(self, payload, status=200):
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", calls, outcome
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)


def test_fault_api_is_alive_and_recovery_opens_before_normal_db_consumers(monkeypatch, recovery_server):
    app = QApplication.instance() or QApplication([])
    base_url, calls, _outcome = recovery_server
    monkeypatch.setenv("HH_API_PORT", str(base_url.rsplit(":", 1)[1]))
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Yes)
    namespace = _startup_functions()
    events = []

    class RestoreDialog(BeholderBackupRestoreDialog):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            QTimer.singleShot(0, self._restore_selected)

    namespace.update({
        "BeholderBackupRestoreDialog": RestoreDialog,
        "stop_api_server": lambda: events.append("server_stop") or True,
        "QApplication": SimpleNamespace(quit=lambda: events.append("quit")),
        "sys": SimpleNamespace(argv=["homework_helper.pyw"], executable="python"),
        "os": SimpleNamespace(execv=lambda executable, arguments: events.append((executable, arguments))),
    })
    manager = SimpleNamespace(
        start_ipc_server=lambda **_kwargs: events.append("recovery_ipc"),
        cleanup=lambda: events.append("cleanup"),
    )
    assert namespace["wait_for_server_ready"](base_url=base_url)
    assert namespace["_is_existing_server_alive"](base_url)
    assert namespace["_prepare_gui_database"](manager) is False
    assert events == ["recovery_ipc", "server_stop", "cleanup", "quit",
                      ("python", ["python", "homework_helper.pyw"])]
    assert calls == [
        ("GET", "/api/gui/ping"), ("GET", "/api/gui/ping"), ("GET", "/api/gui/health"),
        ("GET", "/api/beholder/backups"), ("POST", "/api/beholder/backups/restore-preview"),
        ("POST", "/api/beholder/backups/restore"),
    ]
    app.processEvents()


@pytest.mark.parametrize("failed_stage", ["preview_status", "restore_status"])
def test_restore_failure_keeps_dialog_available_for_retry(monkeypatch, recovery_server, failed_stage):
    app = QApplication.instance() or QApplication([])
    base_url, calls, outcome = recovery_server
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Yes)
    dialog = BeholderBackupRestoreDialog(base_url, database_faulted=True)
    outcome[failed_stage] = 500
    dialog._restore_selected()
    _wait_restore(dialog)
    assert not dialog.restored
    assert dialog._restore_button.isEnabled()
    assert "실패" in dialog._summary.text()
    outcome[failed_stage] = 200
    dialog._restore_selected()
    _wait_restore(dialog)
    assert dialog.restored
    assert dialog.result() == dialog.DialogCode.Accepted
    assert all(path.startswith("/api/beholder/backups") for _method, path in calls)
    dialog.close()
    app.processEvents()


def test_restore_http_runs_off_gui_thread_and_requires_restart(monkeypatch, recovery_server):
    app = QApplication.instance() or QApplication([])
    base_url, calls, outcome = recovery_server
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Yes)
    dialog = BeholderBackupRestoreDialog(base_url)
    outcome["restore_status"] = 500
    dialog._restore_selected()
    assert dialog.restart_required
    _wait_restore(dialog)
    assert not dialog.restored
    assert dialog._restore_button.isEnabled()
    assert "재시작" in dialog._restart_notice.text()
    outcome["restore_status"] = 200
    dialog._restore_selected()
    _wait_restore(dialog)
    assert dialog.restored


def test_incident_restore_is_navigation_not_incident_resolution():
    from src.gui.beholder_dialog import BeholderIncidentDialog
    from PySide6.QtWidgets import QPushButton
    app = QApplication.instance() or QApplication([])
    dialog = BeholderIncidentDialog({})
    button = next(b for b in dialog.findChildren(QPushButton) if b.text() == "백업으로 복구")
    button.click()
    assert dialog.action == "restore_backup"
    assert dialog.result() == dialog.DialogCode.Accepted
