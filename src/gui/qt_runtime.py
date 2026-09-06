"""PySide6 runtime diagnostics and ownership guards."""
from __future__ import annotations

from typing import Any

import PySide6
from PySide6.QtCore import QObject, QThread, qVersion
from shiboken6 import Shiboken


UI_BINDING = "pyside6"
UI_VARIANT = "newgui-2nd"


def binding_diagnostics(renderer: str = "widgets") -> dict[str, str]:
    return {
        "ui_binding": UI_BINDING,
        "binding_version": str(PySide6.__version__),
        "qt_version": str(qVersion()),
        "ui_renderer": str(renderer or "widgets").strip().lower(),
        "ui_variant": UI_VARIANT,
    }


def is_qobject_valid(value: Any) -> bool:
    return isinstance(value, QObject) and Shiboken.isValid(value)


def require_object_thread(owner: QObject, operation: str) -> None:
    """Fail fast when a GUI receiver runs outside its QObject affinity thread."""
    if not is_qobject_valid(owner):
        raise RuntimeError(f"{operation}: QObject wrapper is no longer valid")
    if QThread.currentThread() != owner.thread():
        raise RuntimeError(f"{operation}: receiver executed outside its QObject thread")
