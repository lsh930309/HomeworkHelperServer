"""Shared test configuration and fixtures.

PyQt6, psutil, and windows_toasts are not available in this test environment,
so we mock them at the sys.modules level before any project code is imported.
"""
import sys
import types
from unittest.mock import MagicMock, patch


def _build_pyqt6_mock() -> types.ModuleType:
    """Return a minimal PyQt6 mock that satisfies all project imports."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def pyqtSignal(*args, **kwargs):
        """Minimal pyqtSignal replacement – returns a mock descriptor."""
        sig = MagicMock()
        sig.connect = MagicMock()
        sig.emit = MagicMock()
        sig.disconnect = MagicMock()
        return sig

    def pyqtSlot(*args, **kwargs):
        """Decorator that is a no-op."""
        def decorator(fn):
            return fn
        return decorator

    # ------------------------------------------------------------------
    # QObject base class
    # ------------------------------------------------------------------
    class QObject:
        def __init__(self, *args, **kwargs):
            pass

        def deleteLater(self):
            pass

    # ------------------------------------------------------------------
    # QRunnable
    # ------------------------------------------------------------------
    class QRunnable:
        def __init__(self, *args, **kwargs):
            pass

        def run(self):
            pass

    # ------------------------------------------------------------------
    # QThreadPool
    # ------------------------------------------------------------------
    class QThreadPool(QObject):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._tasks = []

        def setMaxThreadCount(self, n):
            pass

        def start(self, runnable):
            """Execute the runnable synchronously so tests can inspect results."""
            self._tasks.append(runnable)
            # Do NOT auto-run here; tests drive execution explicitly when needed.

    # ------------------------------------------------------------------
    # QTimer
    # ------------------------------------------------------------------
    class QTimer(QObject):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._active = False
            self._single_shot = False
            self._interval = 0
            self._callbacks = []

        def setSingleShot(self, val):
            self._single_shot = val

        def timeout(self):
            pass

        def start(self, interval=None):
            if interval is not None:
                self._interval = interval
            self._active = True

        def stop(self):
            self._active = False

        def isActive(self):
            return self._active

        def deleteLater(self):
            self._active = False

        # Allow `timer.timeout.connect(callback)` usage
        class _TimeoutSignal:
            def __init__(self):
                self._callbacks = []

            def connect(self, cb):
                self._callbacks.append(cb)

            def emit(self):
                for cb in self._callbacks:
                    cb()

        def __init_subclass__(cls, **kwargs):
            super().__init_subclass__(**kwargs)

        # Patch timeout as a per-instance signal
        def _init_timeout(self):
            self.__dict__['timeout'] = QTimer._TimeoutSignal()

    # Monkey-patch QTimer so timeout is an instance attribute
    _original_qt_init = QTimer.__init__

    def _qt_init(self, *args, **kwargs):
        _original_qt_init(self, *args, **kwargs)
        self.__dict__['timeout'] = QTimer._TimeoutSignal()

    QTimer.__init__ = _qt_init

    # singleShot class method
    @staticmethod
    def _singleShot(delay_ms, callback):
        pass  # No-op in tests; tests call callbacks explicitly

    QTimer.singleShot = _singleShot

    # ------------------------------------------------------------------
    # Qt enums / misc
    # ------------------------------------------------------------------
    class Qt:
        class SortOrder:
            AscendingOrder = 0
            DescendingOrder = 1

    # ------------------------------------------------------------------
    # Assemble PyQt6.QtCore module
    # ------------------------------------------------------------------
    QtCore = types.ModuleType("PyQt6.QtCore")
    QtCore.QObject = QObject
    QtCore.QRunnable = QRunnable
    QtCore.QThreadPool = QThreadPool
    QtCore.QTimer = QTimer
    QtCore.pyqtSignal = pyqtSignal
    QtCore.pyqtSlot = pyqtSlot
    QtCore.Qt = Qt

    # ------------------------------------------------------------------
    # Assemble PyQt6 top-level module
    # ------------------------------------------------------------------
    PyQt6 = types.ModuleType("PyQt6")
    PyQt6.QtCore = QtCore

    # Stub out other PyQt6 sub-modules that might be imported
    for submod in [
        "PyQt6.QtWidgets",
        "PyQt6.QtGui",
        "PyQt6.QtNetwork",
        "PyQt6.QtWebEngineWidgets",
    ]:
        stub = types.ModuleType(submod)
        # Provide minimal stubs so wildcard attrs don't raise
        stub.__getattr__ = lambda name, _s=submod: MagicMock(name=f"{_s}.{name}")
        sys.modules[submod] = stub

    return PyQt6, QtCore


# Install the mocks *before* any project module is imported
if "PyQt6" not in sys.modules:
    _pyqt6_mock, _qtcore_mock = _build_pyqt6_mock()
    sys.modules["PyQt6"] = _pyqt6_mock
    sys.modules["PyQt6.QtCore"] = _qtcore_mock


# ------------------------------------------------------------------
# psutil mock
# ------------------------------------------------------------------
if "psutil" not in sys.modules:
    _psutil = types.ModuleType("psutil")

    class _NoSuchProcess(Exception):
        pass

    class _AccessDenied(Exception):
        pass

    class _ZombieProcess(Exception):
        pass

    class _Process:
        def __init__(self, pid=0):
            self.pid = pid
            self.info = {}

        def create_time(self):
            import time
            return time.time()

    _psutil.NoSuchProcess = _NoSuchProcess
    _psutil.AccessDenied = _AccessDenied
    _psutil.ZombieProcess = _ZombieProcess
    _psutil.Process = _Process
    _psutil.process_iter = lambda *args, **kwargs: []

    sys.modules["psutil"] = _psutil


# ------------------------------------------------------------------
# windows_toasts mock
# ------------------------------------------------------------------
if "windows_toasts" not in sys.modules:
    _windows_toasts = types.ModuleType("windows_toasts")
    for _cls_name in [
        "InteractableWindowsToaster",
        "Toast",
        "ToastButton",
        "ToastActivatedEventArgs",
        "ToastDisplayImage",
        "ToastInputTextBox",
    ]:
        setattr(_windows_toasts, _cls_name, MagicMock(name=_cls_name))
    sys.modules["windows_toasts"] = _windows_toasts