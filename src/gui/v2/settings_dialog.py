"""Tabbed v2 settings hub.

This dialog intentionally reuses the mature v1 settings widgets instead of
reimplementing settings persistence.  The child widgets are embedded as tab
pages, their per-dialog buttons are hidden, and one v2 Apply/OK action merges
their outputs into a single full ``GlobalSettings`` save through the existing
DataManager/Beholder boundary.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.data.data_models import GlobalSettings
from src.gui.dialogs import GlobalSettingsDialog, HoYoLabSettingsDialog
from src.gui.sidebar_settings_dialog import SidebarSettingsDialog
from src.gui.v2.theme import build_v2_qss


class SettingsDialogV2(QDialog):
    """Single popup settings hub for v2."""

    def __init__(
        self,
        settings: GlobalSettings,
        parent: Optional[QWidget] = None,
        initial_tab: str | int = 0,
    ):
        super().__init__(parent)
        self.setWindowTitle("설정 · HomeworkHelper v2")
        self.setMinimumWidth(900)
        self.setMinimumHeight(620)
        self._initial_settings = GlobalSettings.from_dict(settings.to_dict())
        self.setStyleSheet(build_v2_qss(getattr(settings, "theme", "system")))
        self._build_ui()
        self.select_tab(initial_tab)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel("v2 설정 허브")
        title.setObjectName("V2Title")
        subtitle = QLabel(
            "일반/알림, 사이드바, 스크린샷, 녹화, HoYoLab 설정을 하나의 popup 안에서 전환합니다."
        )
        subtitle.setObjectName("V2Subtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        self.tabs = QTabWidget(self)
        layout.addWidget(self.tabs, 1)

        self.general_page = GlobalSettingsDialog(self._initial_settings, self)
        self._embed_dialog_page(self.general_page)
        self.tabs.addTab(self.general_page, "일반 · 알림")

        self.sidebar_page = SidebarSettingsDialog(self._initial_settings, self)
        self._embed_dialog_page(self.sidebar_page)
        self.tabs.addTab(self.sidebar_page, "사이드바 · 캡처 · 녹화")

        self.hoyolab_page = HoYoLabSettingsDialog(self)
        self._embed_dialog_page(self.hoyolab_page, keep_buttons=True)
        self._adapt_embedded_hoyolab_page()
        self.tabs.addTab(self.hoyolab_page, "HoYoLab")

        note = QLabel(
            "HoYoLab 탭은 보안상 인증 정보 저장/삭제를 탭 내부 버튼으로 즉시 처리합니다. "
            "나머지 설정은 아래 적용/확인으로 한 번에 저장됩니다."
        )
        note.setObjectName("V2BannerDetail")
        note.setWordWrap(True)
        layout.addWidget(note)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.apply_settings)
        self.button_box.accepted.connect(self._apply_and_accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def select_tab(self, tab: str | int) -> None:
        """Select a tab by index or partial label."""
        if isinstance(tab, int):
            if 0 <= tab < self.tabs.count():
                self.tabs.setCurrentIndex(tab)
            return
        needle = tab.casefold()
        for index in range(self.tabs.count()):
            if needle in self.tabs.tabText(index).casefold():
                self.tabs.setCurrentIndex(index)
                return

    def _embed_dialog_page(self, dialog: QDialog, keep_buttons: bool = False) -> None:
        dialog.setWindowFlags(Qt.WindowType.Widget)
        dialog.setSizeGripEnabled(False)
        if not keep_buttons:
            for button_box in dialog.findChildren(QDialogButtonBox):
                button_box.hide()

    def _adapt_embedded_hoyolab_page(self) -> None:
        """Keep the reused HoYoLab dialog visible when embedded as a v2 tab."""

        button_box = getattr(self.hoyolab_page, "button_box", None)
        if not isinstance(button_box, QDialogButtonBox):
            return

        # The standalone v1 HoYoLab dialog closes itself on Save/Cancel.  In the
        # v2 hub it is a tab page, so saving must be an in-place action.
        for signal in (button_box.accepted, button_box.rejected):
            try:
                signal.disconnect()
            except TypeError:
                pass

        button_box.accepted.connect(self._save_hoyolab_credentials_in_place)
        cancel_button = button_box.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_button:
            cancel_button.hide()

    def _save_hoyolab_credentials_in_place(self) -> bool:
        """Persist HoYoLab credentials without closing the embedded tab page."""

        page = self.hoyolab_page
        ltuid_str = page.ltuid_edit.text().strip()
        ltoken = page.ltoken_edit.text().strip()
        ltmid = page.ltmid_edit.text().strip()

        if ltoken == "••••••••" or ltmid == "••••••••":
            page.extract_status_label.setText("저장된 HoYoLab 인증 정보를 유지합니다.")
            return True

        if not ltuid_str or not ltoken or not ltmid:
            QMessageBox.warning(
                self,
                "입력 오류",
                "모든 필드를 입력하거나 자동 추출을 사용하세요.",
            )
            return False

        try:
            ltuid = int(ltuid_str)
        except ValueError:
            QMessageBox.warning(self, "입력 오류", "LTUID는 숫자여야 합니다.")
            return False

        try:
            from src.services.hoyolab import reset_hoyolab_service
            from src.utils.hoyolab_config import HoYoLabConfig

            config = HoYoLabConfig()
            if config.save_credentials(ltuid, ltoken, ltmid):
                reset_hoyolab_service()
                page._update_status()
                page.extract_status_label.setText("✅ HoYoLab 인증 정보가 저장되었습니다.")
                page.extract_status_label.setStyleSheet("color: #44cc44;")
                QMessageBox.information(self, "저장 완료", "HoYoLab 인증 정보가 저장되었습니다.")
                return True
            QMessageBox.warning(self, "저장 실패", "인증 정보 저장에 실패했습니다.")
        except Exception as e:
            QMessageBox.warning(self, "오류", f"저장 실패: {e}")
        return False

    def _has_pending_hoyolab_credentials(self) -> bool:
        """Return whether the HoYoLab tab contains new unmasked credentials."""

        page = self.hoyolab_page
        ltuid = page.ltuid_edit.text().strip()
        ltoken = page.ltoken_edit.text().strip()
        ltmid = page.ltmid_edit.text().strip()
        if not any((ltuid, ltoken, ltmid)):
            return False
        if ltoken == "••••••••" or ltmid == "••••••••":
            return False
        return True

    def merged_settings(self) -> GlobalSettings:
        """Merge visible v2 settings pages into a full settings object."""

        updated = self.general_page.get_updated_settings()
        # SidebarSettingsDialog copies from its ``_settings`` attribute.  Point it
        # at the general page result so global fields edited on the first tab are
        # not overwritten when sidebar/screenshot/recording fields are merged.
        self.sidebar_page._settings = updated
        return self.sidebar_page.get_updated_settings()

    def apply_settings(self) -> bool:
        parent = self.parent()
        if parent is None or not hasattr(parent, "data_manager"):
            QMessageBox.warning(self, "저장 실패", "설정을 저장할 메인 창 컨텍스트를 찾지 못했습니다.")
            return False

        if hasattr(self.general_page, "scale_combo") and hasattr(self.general_page, "_save_scale_setting"):
            self.general_page._save_scale_setting(self.general_page.scale_combo.currentData())

        if self._has_pending_hoyolab_credentials() and not self._save_hoyolab_credentials_in_place():
            return False

        updated = self.merged_settings()
        self.setStyleSheet(build_v2_qss(getattr(updated, "theme", "system")))
        parent.data_manager.save_global_settings(updated, actor="main_gui_settings")
        parent.launcher.run_as_admin = updated.run_as_admin
        parent._load_always_on_top_setting()
        parent._apply_theme(getattr(updated, "theme", "system"))
        if hasattr(parent, "_apply_v2_visual_system"):
            parent._apply_v2_visual_system()
        if hasattr(parent, "_sidebar_controller"):
            parent._sidebar_controller.apply_settings(updated)
        if hasattr(parent, "_apply_screenshot_settings"):
            parent._apply_screenshot_settings()
        if hasattr(parent, "_apply_recording_settings"):
            parent._apply_recording_settings()
        if hasattr(parent, "apply_startup_setting"):
            parent.apply_startup_setting()
        if hasattr(parent, "populate_process_list"):
            parent.populate_process_list()
        if hasattr(parent, "_refresh_web_button_states"):
            parent._refresh_web_button_states()
        if hasattr(parent, "_adjust_window_height_for_table_rows"):
            parent._adjust_window_height_for_table_rows()

        status_bar = parent.statusBar() if hasattr(parent, "statusBar") else None
        if status_bar:
            status_bar.showMessage("v2 설정 저장됨.", 3000)
        return True

    def _apply_and_accept(self) -> None:
        if self.apply_settings():
            self.accept()
