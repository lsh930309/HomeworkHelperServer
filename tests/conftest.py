"""Shared test fixtures and sys.modules stubs for packages unavailable in CI."""

import sys
import types
import unittest.mock as mock
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Stub out PyQt6 before any project imports touch it
# ---------------------------------------------------------------------------

def _make_pyqt6_stubs():
    """Build minimal PyQt6 stub modules so non-GUI source modules can be imported."""

    # Sentinel for pyqtSignal and pyqtSlot
    def _pyqtSignal(*args, **kwargs):
        return MagicMock()

    def _pyqtSlot(*args, **kwargs):
        def decorator(fn):
            return fn
        return decorator

    class _QObject:
        def __init__(self, *args, **kwargs):
            pass
        def deleteLater(self):
            pass

    class _QRunnable:
        def __init__(self, *args, **kwargs):
            pass
        def run(self):
            pass

    class _QTimer(_QObject):
        def __init__(self, *args, **kwargs):
            super().__init__()
            self._single_shot = False
            self._interval = 0
            self._active = False
            self._callbacks = []

        def setSingleShot(self, val):
            self._single_shot = val

        def start(self, interval=None):
            self._active = True
            if interval is not None:
                self._interval = interval

        def stop(self):
            self._active = False

        def isActive(self):
            return self._active

        def timeout(self):
            pass

        # Allow .timeout.connect(...)
        class _Signal:
            def connect(self, cb):
                pass
            def disconnect(self, cb=None):
                pass

        timeout = _Signal()

        @staticmethod
        def singleShot(ms, callback):
            pass  # don't execute in tests

    class _QThreadPool(_QObject):
        def __init__(self, *args, **kwargs):
            super().__init__()

        def setMaxThreadCount(self, n):
            pass

        def start(self, runnable):
            pass

    # Core module
    qtcore = types.ModuleType("PyQt6.QtCore")
    qtcore.QObject = _QObject
    qtcore.QRunnable = _QRunnable
    qtcore.QTimer = _QTimer
    qtcore.QThreadPool = _QThreadPool
    qtcore.pyqtSignal = _pyqtSignal
    qtcore.pyqtSlot = _pyqtSlot
    qtcore.Qt = MagicMock()
    qtcore.QThread = MagicMock()
    qtcore.pyqtSignal = _pyqtSignal
    qtcore.QUrl = MagicMock()
    qtcore.QEvent = MagicMock()
    qtcore.QSettings = MagicMock()
    qtcore.QPoint = MagicMock()
    qtcore.QRect = MagicMock()
    qtcore.QSize = MagicMock()

    # Widgets module
    qtwidgets = types.ModuleType("PyQt6.QtWidgets")
    for name in [
        "QApplication", "QMainWindow", "QTableWidget", "QTableWidgetItem",
        "QVBoxLayout", "QHBoxLayout", "QWidget", "QHeaderView", "QPushButton",
        "QSizePolicy", "QFileIconProvider", "QAbstractItemView", "QMessageBox",
        "QMenu", "QStyle", "QStatusBar", "QMenuBar", "QAbstractScrollArea",
        "QCheckBox", "QLabel", "QProgressBar", "QSlider", "QToolButton",
    ]:
        setattr(qtwidgets, name, MagicMock())

    # Gui module
    qtgui = types.ModuleType("PyQt6.QtGui")
    for name in [
        "QAction", "QIcon", "QColor", "QDesktopServices", "QFontDatabase",
        "QFont", "QPixmap", "QPalette", "QScreen",
    ]:
        setattr(qtgui, name, MagicMock())

    pyqt6 = types.ModuleType("PyQt6")
    pyqt6.QtCore = qtcore
    pyqt6.QtWidgets = qtwidgets
    pyqt6.QtGui = qtgui

    sys.modules.setdefault("PyQt6", pyqt6)
    sys.modules.setdefault("PyQt6.QtCore", qtcore)
    sys.modules.setdefault("PyQt6.QtWidgets", qtwidgets)
    sys.modules.setdefault("PyQt6.QtGui", qtgui)

    return pyqt6, qtcore, _QObject, _QTimer, _QThreadPool, _pyqtSignal, _pyqtSlot


def _make_psutil_stub():
    """Build a minimal psutil stub."""
    psutil_mod = types.ModuleType("psutil")
    psutil_mod.process_iter = MagicMock(return_value=[])
    psutil_mod.NoSuchProcess = type("NoSuchProcess", (Exception,), {})
    psutil_mod.AccessDenied = type("AccessDenied", (Exception,), {})
    psutil_mod.Process = MagicMock()
    sys.modules.setdefault("psutil", psutil_mod)
    return psutil_mod


def _make_misc_stubs():
    """Stub out Windows-specific and other heavy dependencies."""
    for mod_name in [
        "win32api", "win32con", "win32gui", "win32process", "winshell",
        "pycaw", "pycaw.pycaw",
        "winrt", "winrt.windows", "winrt.windows.gaming", "winrt.windows.gaming.input",
        "Windows", "Windows.Toasts", "winsound",
        "genshin",
        "requests",
        "src.utils.windows",
        "src.utils.admin",
        "src.utils.audio_control",
        "src.utils.browser_cookie_extractor",
        "src.gui.tray_manager",
        "src.gui.gui_notification_handler",
        "src.gui.dialogs",
        "src.gui.volume_panel",
        "src.gui.sidebar",
        "src.gui.sidebar.sidebar_controller",
        "src.core.instance_manager",
        "src.core.launcher",
        "src.core.notifier",
        "src.api.client",
        "src.utils.common",
        "src.utils.process",
        "src.utils.game_preset_manager",
        "src.utils.hoyolab_config",
        "src.utils.launcher_utils",
        "src.recording",
        "src.recording.manager",
        "src.screenshot",
        "src.screenshot.manager",
        "src.screenshot.trigger_dispatcher",
    ]:
        if mod_name not in sys.modules:
            sys.modules[mod_name] = MagicMock()


# Install all stubs immediately when conftest is loaded
_pyqt6_pkg, _qtcore, QObject, QTimer, QThreadPool, pyqtSignal, pyqtSlot = _make_pyqt6_stubs()
_psutil = _make_psutil_stub()
_make_misc_stubs()