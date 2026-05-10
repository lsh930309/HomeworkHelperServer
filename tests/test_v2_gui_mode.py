from pathlib import Path

import pytest

from src.gui.mode import resolve_gui_mode

_QT_APP = None


def _qapp(monkeypatch, tmp_path):
    global _QT_APP
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    from PyQt6.QtWidgets import QApplication

    _QT_APP = QApplication.instance() or QApplication([])
    return _QT_APP


def test_resolve_gui_mode_precedence_cli_env_packaged_file(tmp_path):
    exe = tmp_path / "homework_helper.exe"
    exe.write_text("stub", encoding="utf-8")
    (tmp_path / "gui_mode.txt").write_text("v2\n", encoding="utf-8")

    assert resolve_gui_mode(["app", "--gui-version", "v1"], {"HOMEWORKHELPER_GUI_VERSION": "v2"}, exe) == "v1"
    assert resolve_gui_mode(["app"], {"HOMEWORKHELPER_GUI_VERSION": "v1"}, exe) == "v1"
    assert resolve_gui_mode(["app"], {}, exe) == "v2"


def test_resolve_gui_mode_falls_back_to_v1_for_invalid_values(tmp_path):
    exe = tmp_path / "homework_helper.exe"
    exe.write_text("stub", encoding="utf-8")
    (tmp_path / "gui_mode.txt").write_text("broken-mode\n", encoding="utf-8")

    assert resolve_gui_mode(["app"], {}, exe) == "v1"
    assert resolve_gui_mode(["app"], {"HOMEWORKHELPER_GUI_VERSION": "broken"}, exe) == "v1"
    assert resolve_gui_mode(["app", "--gui-mode=broken"], {"HOMEWORKHELPER_GUI_VERSION": "v2"}, exe) == "v2"


def test_v2_main_window_preserves_v1_feature_surface_and_os_chrome():
    from src.gui.v2.main_window import V2MainWindow, V2StatusBanner
    from src.gui.v2.settings_dialog import SettingsDialogV2

    source = Path("src/gui/v2/main_window.py").read_text(encoding="utf-8")

    assert V2MainWindow.__name__ == "V2MainWindow"
    assert V2StatusBanner.__name__ == "V2StatusBanner"
    assert SettingsDialogV2.__name__ == "SettingsDialogV2"
    assert "class V2MainWindow(MainWindow)" in source
    assert "FramelessWindowHint" in source
    assert "& ~Qt.WindowType.FramelessWindowHint" in source
    assert "SettingsDialogV2" in source
    assert "V2StatusBanner" in source
    assert "def populate_process_list" in source
    assert "super().populate_process_list()" in source
    assert "def update_process_statuses_only" in source
    assert "super().update_process_statuses_only()" in source
    assert "actor=\"main_gui_settings\"" in Path("src/gui/v2/settings_dialog.py").read_text(encoding="utf-8")
    assert "def _apply_v2_status_visibility" in source
    assert "setColumnHidden(self.COL_STATUS, True)" in source
    assert "숨겨진 v1 호환 상태 컬럼" in source


def test_v2_gui_does_not_introduce_direct_db_write_paths():
    forbidden_snippets = [
        "sqlite3",
        "create_engine",
        "Session(",
        "get_db(",
        "db.commit",
        ".commit()",
        "crud.",
    ]
    for path in Path("src/gui/v2").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for snippet in forbidden_snippets:
            assert snippet not in source, f"{path} must keep writes behind existing API/CRUD/Beholder boundaries"


def test_v2_process_rows_keep_hidden_status_data_with_visual_indicator(monkeypatch, tmp_path):
    _qapp(monkeypatch, tmp_path)
    from types import SimpleNamespace
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QPushButton, QTableWidget, QTableWidgetItem
    from src.core.scheduler import PROC_STATE_RUNNING
    from src.gui.v2.main_window import V2MainWindow

    window = V2MainWindow.__new__(V2MainWindow)
    window.process_table = QTableWidget(1, 5)
    window.data_manager = SimpleNamespace(
        global_settings=SimpleNamespace(theme="light"),
        get_process_by_id=lambda process_id: SimpleNamespace(
            name="테스트 게임",
            preferred_launch_type="launcher",
        ),
    )
    icon_item = QTableWidgetItem()
    name_item = QTableWidgetItem("테스트 게임")
    name_item.setData(Qt.ItemDataRole.UserRole, "process-1")
    status_item = QTableWidgetItem(PROC_STATE_RUNNING)
    launch_button = QPushButton("실행")
    window.process_table.setItem(0, window.COL_ICON, icon_item)
    window.process_table.setItem(0, window.COL_NAME, name_item)
    window.process_table.setItem(0, window.COL_STATUS, status_item)
    window.process_table.setCellWidget(0, window.COL_LAUNCH_BTN, launch_button)

    V2MainWindow._decorate_v2_process_rows(window)

    assert window.process_table.isColumnHidden(window.COL_STATUS)
    assert icon_item.background().color().isValid()
    assert icon_item.toolTip() == f"상태: {PROC_STATE_RUNNING}"
    assert "숨겨진 v1 호환 상태 컬럼" in status_item.whatsThis()
    assert launch_button.text() == "▶"
    assert "방식: launcher" in launch_button.toolTip()
    assert PROC_STATE_RUNNING in name_item.whatsThis()


def test_homework_helper_selects_v2_window_from_resolved_mode():
    entrypoint = Path("homework_helper.pyw").read_text(encoding="utf-8")

    assert "resolve_gui_mode" in entrypoint
    assert "V2MainWindow if gui_mode == GUI_MODE_V2 else MainWindow" in entrypoint
    assert "gui_mode.txt" in Path("src/gui/mode.py").read_text(encoding="utf-8")


def test_v2_theme_uses_light_dark_tokens_without_background_gradients():
    from src.gui.v2.theme import build_v2_qss

    light_qss = build_v2_qss("light")
    dark_qss = build_v2_qss("dark")

    for qss in (light_qss, dark_qss):
        assert "QMainWindow#HomeworkHelperV2" in qss
        assert "QFrame#V2Topbar" in qss
        assert "QFrame#V2MessageBanner" in qss
        assert "linear-gradient" not in qss
        assert "radial-gradient" not in qss


def test_v2_status_banner_uses_summary_and_progressive_detail(monkeypatch, tmp_path):
    _qapp(monkeypatch, tmp_path)
    from src.gui.v2.main_window import V2StatusBanner

    banner = V2StatusBanner()
    try:
        banner.show_message("실행 요청 완료: " + ("긴 대상 경로 " * 12) + "\n전체 상세 메시지", timeout_ms=0)

        assert not banner.isHidden()
        assert banner.detail_button.isVisible()
        assert banner.summary_label.text().endswith("...")
        assert not banner.detail_label.isVisible()

        banner.detail_button.setChecked(True)
        assert banner.detail_label.isVisible()
        assert "전체 상세 메시지" in banner.detail_label.text()
    finally:
        banner.deleteLater()


def test_v2_status_banner_ignores_stale_auto_hide_timers(monkeypatch, tmp_path):
    _qapp(monkeypatch, tmp_path)
    import src.gui.v2.main_window as main_window

    callbacks = []
    monkeypatch.setattr(main_window.QTimer, "singleShot", lambda _ms, callback: callbacks.append(callback))
    banner = main_window.V2StatusBanner()
    try:
        banner.show_message("첫 번째 메시지", timeout_ms=100)
        banner.show_message("두 번째 메시지", timeout_ms=100)

        callbacks[0]()
        assert banner.isVisible()
        assert banner.summary_label.text() == "두 번째 메시지"

        callbacks[1]()
        assert banner.isHidden()
    finally:
        banner.deleteLater()


def test_v2_settings_hub_merges_pages_without_dropping_v1_fields(monkeypatch, tmp_path):
    _qapp(monkeypatch, tmp_path)
    from src.data.data_models import GlobalSettings
    from src.gui.v2.settings_dialog import SettingsDialogV2

    settings = GlobalSettings(
        theme="dark",
        hide_on_game=True,
        notify_on_daily_reset=True,
        sidebar_height_ratio=0.7,
        screenshot_save_dir="C:/Shots",
        recording_enabled=False,
        obs_password="secret",
    )
    dialog = SettingsDialogV2(settings)
    try:
        dialog.general_page.theme_light_rb.setChecked(True)
        dialog.general_page.hide_on_game_checkbox.setChecked(False)
        dialog.general_page.notify_on_daily_reset_checkbox.setChecked(False)
        dialog.sidebar_page._height_spin.setValue(0.55)
        dialog.sidebar_page._ss_save_dir_edit.setText("D:/Captures")
        dialog.sidebar_page._rec_enabled_cb.setChecked(True)
        dialog.sidebar_page._obs_password_edit.setText("secret2")

        merged = dialog.merged_settings()

        assert merged.theme == "light"
        assert merged.hide_on_game is False
        assert merged.notify_on_daily_reset is False
        assert merged.sidebar_height_ratio == 0.55
        assert merged.screenshot_save_dir == "D:/Captures"
        assert merged.recording_enabled is True
        assert merged.obs_password == "secret2"
    finally:
        dialog.deleteLater()


def test_v2_settings_hub_can_open_directly_to_feature_tabs(monkeypatch, tmp_path):
    _qapp(monkeypatch, tmp_path)
    from src.data.data_models import GlobalSettings
    from src.gui.v2.settings_dialog import SettingsDialogV2

    dialog = SettingsDialogV2(GlobalSettings(), initial_tab="HoYoLab")
    try:
        assert dialog.tabs.tabText(dialog.tabs.currentIndex()) == "HoYoLab"
        dialog.select_tab("사이드바")
        assert "사이드바" in dialog.tabs.tabText(dialog.tabs.currentIndex())
    finally:
        dialog.deleteLater()


def test_v2_settings_hub_uses_v2_theme_tokens_standalone(monkeypatch, tmp_path):
    _qapp(monkeypatch, tmp_path)
    from src.data.data_models import GlobalSettings
    from src.gui.v2.settings_dialog import SettingsDialogV2

    dialog = SettingsDialogV2(GlobalSettings(theme="dark"))
    try:
        qss = dialog.styleSheet()
        assert "QDialog" in qss
        assert "QTabWidget::pane" in qss
        assert "#171f2f" in qss
        assert "linear-gradient" not in qss
        assert "radial-gradient" not in qss
    finally:
        dialog.deleteLater()


def test_v2_hoyolab_tab_saves_credentials_in_place(monkeypatch, tmp_path):
    _qapp(monkeypatch, tmp_path)
    from PyQt6.QtWidgets import QDialogButtonBox, QMessageBox
    from src.data.data_models import GlobalSettings
    from src.gui.v2.settings_dialog import SettingsDialogV2
    from src.services import hoyolab as hoyolab_service
    from src.utils import hoyolab_config

    monkeypatch.setattr(hoyolab_config.HoYoLabConfig, "load_credentials", lambda self: None)
    monkeypatch.setattr(hoyolab_config.HoYoLabConfig, "is_configured", lambda self: False)

    dialog = SettingsDialogV2(GlobalSettings(), initial_tab="HoYoLab")
    try:
        page = dialog.hoyolab_page
        page.accept = lambda: pytest.fail("embedded HoYoLab tab must not accept/close itself")
        page.reject = lambda: pytest.fail("embedded HoYoLab tab must not reject/close itself")
        page.ltuid_edit.setText("12345")
        page.ltoken_edit.setText("token")
        page.ltmid_edit.setText("mid")

        saved: dict[str, object] = {}

        def save_credentials(_self, ltuid, ltoken, ltmid):
            saved.update({"ltuid": ltuid, "ltoken": ltoken, "ltmid": ltmid})
            return True

        monkeypatch.setattr(hoyolab_config.HoYoLabConfig, "save_credentials", save_credentials)
        monkeypatch.setattr(hoyolab_config.HoYoLabConfig, "is_configured", lambda self: True)
        monkeypatch.setattr(hoyolab_service, "reset_hoyolab_service", lambda: None)
        monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
        monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: pytest.fail("unexpected warning"))

        assert dialog._save_hoyolab_credentials_in_place()
        assert saved == {"ltuid": 12345, "ltoken": "token", "ltmid": "mid"}
        assert "저장되었습니다" in page.extract_status_label.text()
        assert dialog.tabs.widget(dialog.tabs.currentIndex()) is page
        assert page.button_box.button(QDialogButtonBox.StandardButton.Cancel).isHidden()
    finally:
        dialog.deleteLater()


def test_v2_settings_hub_apply_saves_pending_hoyolab_credentials(monkeypatch, tmp_path):
    _qapp(monkeypatch, tmp_path)
    from types import SimpleNamespace
    from PyQt6.QtWidgets import QMessageBox, QWidget
    from src.data.data_models import GlobalSettings
    from src.gui.v2.settings_dialog import SettingsDialogV2
    from src.services import hoyolab as hoyolab_service
    from src.utils import hoyolab_config

    class Parent(QWidget):
        def __init__(self):
            super().__init__()
            self.saved_settings = None
            self.saved_actor = None
            self.launcher = SimpleNamespace(run_as_admin=False)
            self.data_manager = SimpleNamespace(
                global_settings=GlobalSettings(),
                save_global_settings=self._save_global_settings,
            )

        def _save_global_settings(self, settings, actor=None):
            self.saved_settings = settings
            self.saved_actor = actor
            self.data_manager.global_settings = settings

        def _load_always_on_top_setting(self):
            pass

        def _apply_theme(self, _theme):
            pass

        def apply_startup_setting(self):
            pass

        def statusBar(self):
            return None

    monkeypatch.setattr(hoyolab_config.HoYoLabConfig, "load_credentials", lambda self: None)
    monkeypatch.setattr(hoyolab_config.HoYoLabConfig, "is_configured", lambda self: False)

    parent = Parent()
    dialog = SettingsDialogV2(GlobalSettings(), parent, initial_tab="HoYoLab")
    try:
        dialog.hoyolab_page.ltuid_edit.setText("67890")
        dialog.hoyolab_page.ltoken_edit.setText("token2")
        dialog.hoyolab_page.ltmid_edit.setText("mid2")

        saved: dict[str, object] = {}

        def save_credentials(_self, ltuid, ltoken, ltmid):
            saved.update({"ltuid": ltuid, "ltoken": ltoken, "ltmid": ltmid})
            return True

        monkeypatch.setattr(hoyolab_config.HoYoLabConfig, "save_credentials", save_credentials)
        monkeypatch.setattr(hoyolab_config.HoYoLabConfig, "is_configured", lambda self: True)
        monkeypatch.setattr(hoyolab_service, "reset_hoyolab_service", lambda: None)
        monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
        monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: pytest.fail("unexpected warning"))

        assert dialog.apply_settings()
        assert saved == {"ltuid": 67890, "ltoken": "token2", "ltmid": "mid2"}
        assert parent.saved_actor == "main_gui_settings"
    finally:
        dialog.deleteLater()
        parent.deleteLater()


def test_v2_routes_legacy_settings_menu_entries_to_single_hub():
    source = Path("src/gui/v2/main_window.py").read_text(encoding="utf-8")

    assert "def open_sidebar_settings_dialog" in source
    assert 'self._open_settings_hub("사이드바")' in source
    assert "def open_hoyolab_settings_dialog" in source
    assert 'self._open_settings_hub("HoYoLab")' in source
