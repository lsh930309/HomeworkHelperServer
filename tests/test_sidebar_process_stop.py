import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.data.data_models import ManagedProcess
import src.gui.sidebar.sidebar_widget as sidebar_module


def make_sidebar(monkeypatch):
    from src.gui.main_window import MainWindow
    monkeypatch.setattr(MainWindow, "INSTANCE", None)
    app = QApplication.instance() or QApplication([])
    process = ManagedProcess(id="game", name="Game", monitoring_path="/games/game.exe", launch_path="/games/launcher.exe")
    settings = SimpleNamespace(run_as_admin=True)
    sidebar = sidebar_module.SidebarWidget(SimpleNamespace(managed_processes=[process], global_settings=settings))
    return app, sidebar, process, settings


def test_sidebar_queues_captured_identity_and_setting_before_background_work(monkeypatch):
    app, sidebar, process, settings = make_sidebar(monkeypatch)
    queued = []
    monkeypatch.setattr(sidebar_module.QThreadPool, "globalInstance", lambda: SimpleNamespace(start=queued.append))

    sidebar._kill_process("game", "/games/game.exe", 42, 123.0)
    process.monitoring_path = "/games/changed.exe"
    settings.run_as_admin = False
    calls = []
    monkeypatch.setattr(sidebar_module, "terminate_managed_process",
                        lambda snapshot, **kwargs: calls.append((snapshot.monitoring_path, kwargs)) or {"accepted": True, "message": "requested"})
    queued[0].run()
    app.processEvents()

    assert calls == [("/games/game.exe", {"run_as_admin": True, "pid": 42, "create_time": 123.0})]
    sidebar.close()


def test_sidebar_rejects_button_for_removed_registration(monkeypatch):
    _app, sidebar, _process, _settings = make_sidebar(monkeypatch)
    sidebar._data_manager.managed_processes = []
    monkeypatch.setattr(sidebar_module.QThreadPool, "globalInstance",
                        lambda: SimpleNamespace(start=lambda _task: (_ for _ in ()).throw(AssertionError("removed game must not enqueue a stop"))))

    sidebar._kill_process("game", "/games/game.exe", 42, 123.0)

    assert "등록 대상" in sidebar._process_stop_status.text()
    sidebar.close()


def test_sidebar_surfaces_privilege_service_failure(monkeypatch):
    app, sidebar, _process, _settings = make_sidebar(monkeypatch)
    queued = []
    monkeypatch.setattr(sidebar_module.QThreadPool, "globalInstance", lambda: SimpleNamespace(start=queued.append))
    calls = []
    monkeypatch.setattr(sidebar, "slide_out", lambda: calls.append("hidden"))

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("관리자 서비스에 연결할 수 없습니다.")

    monkeypatch.setattr(sidebar_module, "terminate_managed_process", unavailable)
    sidebar._kill_process("game", "/games/game.exe", 42, 123.0)
    queued[0].run()
    app.processEvents()

    assert "관리자 서비스" in sidebar._process_stop_status.text()
    assert calls == []
    sidebar.close()
