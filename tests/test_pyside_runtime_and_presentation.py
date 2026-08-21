import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import QApplication, QMainWindow, QPushButton, QVBoxLayout, QWidget
from shiboken6 import Shiboken

from src.gui.presentation import PresentationController, resolve_ui_renderer
from src.gui.qt_runtime import binding_diagnostics, is_qobject_valid, require_object_thread
from src.gui.widgets_style import apply_modern_widgets_style


def _qapp():
    return QApplication.instance() or QApplication([])


def test_runtime_reports_only_pyside6_binding():
    diagnostics = binding_diagnostics("widgets")
    assert diagnostics["ui_binding"] == "pyside6"
    assert diagnostics["binding_version"].startswith("6.11.")
    assert diagnostics["qt_version"].startswith("6.11.")
    assert diagnostics["ui_variant"] == "newgui-2nd"


def test_qobject_validity_and_thread_guard_follow_shiboken_lifetime():
    _qapp()
    owner = QObject()
    assert is_qobject_valid(owner)
    require_object_thread(owner, "test")
    Shiboken.delete(owner)
    assert not is_qobject_valid(owner)
    with pytest.raises(RuntimeError, match="no longer valid"):
        require_object_thread(owner, "test")


def test_renderer_selection_defaults_to_widgets_and_accepts_qml(monkeypatch):
    monkeypatch.delenv("HH_UI_RENDERER", raising=False)
    assert resolve_ui_renderer([]) == "widgets"
    assert resolve_ui_renderer(["--ui-renderer=qml"]) == "qml"
    monkeypatch.setenv("HH_UI_RENDERER", "qml")
    assert resolve_ui_renderer([]) == "qml"
    with pytest.raises(ValueError, match="지원하지 않는"):
        resolve_ui_renderer(["--ui-renderer=web"])


def test_modern_widgets_style_marks_surface_and_primary_action():
    _qapp()
    window = QMainWindow()
    central = QWidget(window)
    central.setLayout(QVBoxLayout())
    window.setCentralWidget(central)
    window.add_game_button = QPushButton("새 게임 추가", central)
    central.layout().addWidget(window.add_game_button)
    apply_modern_widgets_style(window, dark=False)
    assert central.objectName() == "hhMainSurface"
    assert window.add_game_button.property("hhRole") == "primaryAction"
    assert "#f5f6f8" in window.styleSheet()


def test_slot_receiver_runs_in_its_qobject_thread():
    app = _qapp()
    thread = QThread()

    class Emitter(QObject):
        fired = Signal()

        @Slot()
        def emit_from_worker(self):
            self.fired.emit()

    class Receiver(QObject):
        def __init__(self):
            super().__init__()
            self.observed = None

        @Slot()
        def receive(self):
            self.observed = QThread.currentThread()

    emitter = Emitter()
    receiver = Receiver()
    emitter.moveToThread(thread)
    emitter.fired.connect(receiver.receive)
    thread.started.connect(emitter.emit_from_worker)
    thread.start()
    deadline = 200
    while receiver.observed is None and deadline:
        app.processEvents()
        QThread.msleep(1)
        deadline -= 1
    thread.quit()
    assert thread.wait(1_000)
    assert receiver.observed == receiver.thread()


class _RefreshTimer(QObject):
    timeout = Signal()


class _FakeWindow(QObject):
    request_table_refresh_signal = Signal()

    def __init__(self):
        super().__init__()
        self.ui_refresh_timer = _RefreshTimer(self)
        self.data_manager = SimpleNamespace(
            managed_processes=[],
            global_settings=SimpleNamespace(),
        )
        self.scheduler = SimpleNamespace(determine_process_visual_status=lambda *_args: "대기")
        self.presentation = None

    def _calculate_progress_percentage(self, *_args):
        return 0.0, ""

    def _is_effective_dark_theme(self):
        return False

    def set_presentation_window(self, window, facade=None):
        self.presentation = (window, facade)

    def hide(self):
        return None


def test_qml_candidate_loads_as_independent_quick_window():
    app = _qapp()
    owner = _FakeWindow()
    controller = PresentationController(owner, "qml")
    assert controller.engine is not None
    assert controller.window is not owner
    assert owner.presentation[0] is controller.window
    controller.show()
    app.processEvents()
    assert controller.window.isVisible()
    controller.window.hide()
    controller.shutdown()
