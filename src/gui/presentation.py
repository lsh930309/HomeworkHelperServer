"""Select and own the Windows host presentation surface."""
from __future__ import annotations

import logging
import os
from importlib import import_module
from pathlib import Path
from typing import Sequence

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QUrl, Slot

from src.gui.host_ui_facade import HostUiFacade
from src.gui.qt_runtime import binding_diagnostics

logger = logging.getLogger(__name__)

VALID_RENDERERS = frozenset({"widgets", "qml"})


def resolve_ui_renderer(argv: Sequence[str] | None = None) -> str:
    renderer = os.environ.get("HH_UI_RENDERER", "").strip().lower()
    for argument in list(argv or ()):
        if argument.startswith("--ui-renderer="):
            renderer = argument.split("=", 1)[1].strip().lower()
    if not renderer:
        renderer = "widgets"
    if renderer not in VALID_RENDERERS:
        raise ValueError(f"지원하지 않는 UI renderer입니다: {renderer}")
    return renderer


class PresentationController(QObject):
    def __init__(self, main_window, renderer: str):
        super().__init__(main_window)
        self.main_window = main_window
        self.renderer = renderer
        self.facade = HostUiFacade(main_window, self)
        self.engine: QObject | None = None
        self.window = main_window
        self._shutdown = False

        if renderer == "qml":
            # Qt Quick is an opt-in candidate in packaged builds. Keeping these
            # imports dynamic prevents the default Widgets onedir from carrying
            # the complete QML/Quick runtime. Set HH_INCLUDE_QML=1 while running
            # PyInstaller for the separately measured QML candidate.
            QQmlApplicationEngine = import_module("PySide6.QtQml").QQmlApplicationEngine
            QQuickStyle = import_module("PySide6.QtQuickControls2").QQuickStyle
            QQuickStyle.setStyle("Basic")
            self.engine = QQmlApplicationEngine(self)
            self.engine.rootContext().setContextProperty("hostUi", self.facade)
            qml_path = Path(__file__).with_name("qml") / "HostWindow.qml"
            self.engine.load(QUrl.fromLocalFile(str(qml_path)))
            roots = self.engine.rootObjects()
            if not roots:
                raise RuntimeError(f"QML presentation을 로드하지 못했습니다: {qml_path}")
            self.window = roots[0]
            self.facade.set_presentation_window(self.window)
            self.main_window.set_presentation_window(self.window, self.facade)
        else:
            self.main_window.set_presentation_window(self.main_window, self.facade)

        logger.info("UI runtime: %s", binding_diagnostics(renderer))
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)

    def show(self) -> None:
        if self.renderer == "qml":
            self.main_window.hide()
            self.facade.activateAndShow()
            return
        self.main_window.show()

    @Slot()
    def shutdown(self) -> None:
        if self._shutdown:
            return
        self._shutdown = True
        if self.engine is not None:
            for root in self.engine.rootObjects():
                root.hide()
                root.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            self.engine.deleteLater()
            self.engine = None
