import os
import subprocess
import sys
import textwrap
import pytest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.data.data_models import ManagedProcess
import src.gui.sidebar.sidebar_widget as sidebar_module


@pytest.fixture
def sidebar_state(monkeypatch):
    from src.gui.main_window import MainWindow
    monkeypatch.setattr(MainWindow, "INSTANCE", None)
    app = QApplication.instance() or QApplication([])
    process = ManagedProcess(id="game", name="Game", monitoring_path="/games/game.exe", launch_path="/games/launcher.exe")
    settings = SimpleNamespace(run_as_admin=True)
    sidebar = sidebar_module.SidebarWidget(SimpleNamespace(managed_processes=[process], global_settings=settings))
    # Contract tests execute a captured runnable synchronously; they should not
    # process pending GUI events or animate windows owned by unrelated tests.
    monkeypatch.setattr(sidebar, "slide_out", lambda: None)
    monkeypatch.setattr(sidebar, "_reset_auto_hide", lambda: None)
    try:
        yield app, sidebar, process, settings
    finally:
        assert sidebar.cleanup(deadline_ms=200)
        sidebar.close()


def test_sidebar_queues_captured_identity_and_setting_before_background_work(monkeypatch, sidebar_state):
    _app, sidebar, process, settings = sidebar_state
    queued = []
    monkeypatch.setattr(sidebar_module.QThreadPool, "globalInstance", lambda: SimpleNamespace(start=queued.append))

    sidebar._kill_process("game", "/games/game.exe", 42, 123.0)
    process.monitoring_path = "/games/changed.exe"
    settings.run_as_admin = False
    calls = []
    monkeypatch.setattr(sidebar_module, "terminate_managed_process",
                        lambda snapshot, **kwargs: calls.append((snapshot.monitoring_path, kwargs)) or {"accepted": True, "message": "requested"})
    queued[0].run()

    assert calls == [("/games/game.exe", {"run_as_admin": True, "pid": 42, "create_time": 123.0})]


def test_sidebar_rejects_button_for_removed_registration(monkeypatch, sidebar_state):
    _app, sidebar, _process, _settings = sidebar_state
    sidebar._data_manager.managed_processes = []
    monkeypatch.setattr(sidebar_module.QThreadPool, "globalInstance",
                        lambda: SimpleNamespace(start=lambda _task: (_ for _ in ()).throw(AssertionError("removed game must not enqueue a stop"))))

    sidebar._kill_process("game", "/games/game.exe", 42, 123.0)

    assert "등록 대상" in sidebar._process_stop_status.text()


def test_sidebar_surfaces_privilege_service_failure(monkeypatch, sidebar_state):
    _app, sidebar, _process, _settings = sidebar_state
    queued = []
    monkeypatch.setattr(sidebar_module.QThreadPool, "globalInstance", lambda: SimpleNamespace(start=queued.append))
    calls = []
    monkeypatch.setattr(sidebar, "slide_out", lambda: calls.append("hidden"))

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("관리자 서비스에 연결할 수 없습니다.")

    monkeypatch.setattr(sidebar_module, "terminate_managed_process", unavailable)
    sidebar._kill_process("game", "/games/game.exe", 42, 123.0)
    queued[0].run()

    assert "관리자 서비스" in sidebar._process_stop_status.text()
    assert calls == []


def test_actual_stop_worker_delivers_product_slot_on_gui_thread_in_isolated_process(tmp_path):
    # Fresh Qt ownership is required: this is a worker/GUI lifetime test, not a
    # request to pump unrelated windows left by another test module.
    script = textwrap.dedent("""
        from types import SimpleNamespace
        from PySide6.QtCore import QEventLoop, QThread, QThreadPool, QTimer
        from PySide6.QtWidgets import QApplication
        from src.data.data_models import ManagedProcess
        from src.gui.main_window import MainWindow
        from src.gui.sidebar import sidebar_widget as module

        app = QApplication([])
        MainWindow.INSTANCE = None
        process = ManagedProcess(id='game', name='Game', monitoring_path='/game.exe', launch_path='/game.exe')
        sidebar = module.SidebarWidget(SimpleNamespace(managed_processes=[process], global_settings=SimpleNamespace(run_as_admin=True)))
        worker_on_gui = []
        receiver_on_gui = []
        def stop(*args, **kwargs):
            worker_on_gui.append(QThread.currentThread() == app.thread())
            return {'accepted': False, 'status': 'failed', 'message': 'controlled result'}
        module.terminate_managed_process = stop
        original_set_text = sidebar._process_stop_status.setText
        def set_text(value):
            receiver_on_gui.append(QThread.currentThread() == app.thread())
            original_set_text(value)
        sidebar._process_stop_status.setText = set_text
        sidebar._reset_auto_hide = lambda: None
        loop = QEventLoop()
        sidebar._process_stop_signals.completed.connect(loop.quit)
        pool = QThreadPool()
        pool.setMaxThreadCount(1)
        task = module._ProcessStopTask(process, 42, 123.0, True, sidebar._process_stop_signals)
        pool.start(task)
        QTimer.singleShot(2000, loop.quit)
        loop.exec()
        assert worker_on_gui == [False], worker_on_gui
        assert receiver_on_gui == [True], receiver_on_gui
        assert 'controlled result' in sidebar._process_stop_status.text()
        assert pool.waitForDone(1000)
        assert sidebar.cleanup(deadline_ms=200)
        sidebar.close()
    """)
    environment = os.environ.copy()
    environment['QT_QPA_PLATFORM'] = 'offscreen'
    environment['HH_TEST_APPDATA_DIR'] = str(tmp_path / 'appdata')
    result = subprocess.run([sys.executable, '-c', script], env=environment, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
