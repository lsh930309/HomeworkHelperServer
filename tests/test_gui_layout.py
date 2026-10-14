import os
import json
import subprocess
import sys
import textwrap
from pathlib import Path
from types import MethodType, SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QImage, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QProgressBar, QPushButton, QStyle, QStyleOptionButton

from src.data.data_models import (
    GlobalSettings,
    ManagedProcess,
    WebShortcut,
    SIDEBAR_MODE_ALWAYS,
    SIDEBAR_MODE_DISABLED,
    SIDEBAR_MODE_GAME,
)
from src.core.process_monitor import ProcessMonitorTickResult
import src.gui.sidebar.edge_trigger_window as edge_trigger_module
from src.gui.sidebar.edge_trigger_window import EdgeTriggerWindow


class _Noop:
    def __init__(self, *_args, **_kwargs):
        pass

    def __getattr__(self, _name):
        def _noop(*_args, **_kwargs):
            return None

        return _noop


class _FakeApiClient:
    def __init__(self, processes):
        self.app_instance_id = "gui-layout-test"
        self.managed_processes = processes
        self.web_shortcuts = []
        self.global_settings = GlobalSettings(
            run_on_startup=False,
            run_as_admin=False,
            sidebar_enabled=False,
            screenshot_enabled=False,
            screenshot_gamepad_trigger=False,
            recording_enabled=False,
        )

    def get_process_by_id(self, process_id):
        return next((p for p in self.managed_processes if p.id == process_id), None)

    def get_web_shortcut_by_id(self, shortcut_id):
        return next((s for s in self.web_shortcuts if s.id == shortcut_id), None)

    def pop_latest_beholder_incident(self):
        return None

    def get_active_beholder_incidents(self):
        return []

    def get_beholder_backups(self):
        return []

    def send_runtime_heartbeat(self, **_kwargs):
        return None

    def reconcile_open_sessions(self, _running_ids):
        return []

    def save_global_settings(self, settings, actor=None):
        self.global_settings = settings
        return True


def _qapp():
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("HomeworkHelper Test")
    return app


def _patch_main_window_deps(monkeypatch, tmp_path):
    import src.gui.main_window as main_window
    from src.recording.manager import RecordingManager
    from src.api.client import BackgroundApiTransport, BackgroundHttpResult

    class LayoutTimer(QTimer):
        @staticmethod
        def singleShot(interval, callback):
            # Each layout window is destroyed while this shared test QApplication
            # stays alive. Bind queued callbacks to the window's QObject lifetime.
            QTimer.singleShot(interval, main_window.MainWindow.INSTANCE, callback)

    monkeypatch.setattr(main_window, "QTimer", LayoutTimer)

    # Layout tests already use a fake data manager. Keep its background HTTP,
    # Tailscale and privilege-service observations on that same test boundary.
    def empty_api_result(*_args, **_kwargs):
        return BackgroundHttpResult(
            status_code=200, elapsed_seconds=0.0,
            payload={"incidents": [], "logs": [], "skipped": [], "attempted": 0},
        )

    monkeypatch.setattr(BackgroundApiTransport, "get_json", empty_api_result)
    monkeypatch.setattr(BackgroundApiTransport, "post_json", empty_api_result)
    monkeypatch.setattr(main_window, "tailscale_status", lambda **_kwargs: SimpleNamespace(
        ready=False, installed=False, self_ips=(), message="테스트 Tailscale 미설정",
    ))
    monkeypatch.setattr(main_window, "privilege_service_status", lambda: (False, "테스트 권한 서비스 미설정"))
    # Layout fixtures never contact the installed service or launch a real OBS.
    monkeypatch.setattr(RecordingManager, "prepare_for_startup",
                        lambda self, settings: self._set_settings(settings))

    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(main_window.IconDownloader, "start", lambda self: None)
    monkeypatch.setattr(main_window, "TrayManager", _Noop)
    monkeypatch.setattr(main_window, "Notifier", _Noop)
    monkeypatch.setattr(main_window, "SidebarController", _Noop)
    monkeypatch.setattr(main_window.GamePresetManager, "USER_CONFIG_DIR", tmp_path / "HomeworkHelper")
    monkeypatch.setattr(
        main_window.GamePresetManager,
        "USER_PRESET_FILE",
        tmp_path / "HomeworkHelper" / "game_presets_user.json",
    )
    return main_window


def test_global_settings_derives_sidebar_mode_from_legacy_bool():
    disabled = GlobalSettings(sidebar_enabled=False)
    assert disabled.sidebar_mode == SIDEBAR_MODE_DISABLED
    assert disabled.sidebar_enabled is False

    restored = GlobalSettings.from_dict({"sidebar_enabled": True, "sidebar_mode": SIDEBAR_MODE_ALWAYS})
    assert restored.sidebar_mode == SIDEBAR_MODE_ALWAYS
    assert restored.sidebar_enabled is True
    assert restored.sidebar_handle_auto_hide is True

    ranged = GlobalSettings.from_dict({
        "sidebar_trigger_y_start": 0.8,
        "sidebar_trigger_y_end": 0.2,
        "sidebar_handle_auto_hide": False,
    })
    assert ranged.sidebar_trigger_y_start == 0.2
    assert ranged.sidebar_trigger_y_end == 0.8
    assert ranged.sidebar_handle_auto_hide is False

    remote_default = GlobalSettings.from_dict({})
    assert remote_default.remote_server_mode_enabled is False
    remote_enabled = GlobalSettings.from_dict({"remote_server_mode_enabled": True})
    assert remote_enabled.remote_server_mode_enabled is True


def test_main_window_settings_menu_exposes_remote_settings_dialog():
    source = Path("src/gui/main_window.py").read_text(encoding="utf-8")
    dialog_source = Path("src/gui/dialogs.py").read_text(encoding="utf-8")

    assert "def _text_menu_action" in source
    assert "setIconVisibleInMenu(False)" in source
    assert '_text_menu_action("앱 설정...", self.open_global_settings_dialog)' in source
    assert '_text_menu_action("원격 설정...", self.open_remote_settings_dialog)' in source
    assert '_text_menu_action("자원/출석 관리...", self.open_hoyolab_settings_dialog)' in source
    assert '_text_menu_action("HoYoLab 설정...", self.open_hoyolab_settings_dialog)' not in source
    assert source.index('_text_menu_action("앱 설정..."') < source.index('_text_menu_action("원격 설정..."')
    assert source.index('_text_menu_action("원격 설정..."') < source.index('_text_menu_action("사이드바 설정..."')
    assert "open_remote_settings_dialog" in source
    assert "RemoteSettingsDialog" in source
    assert 'QAction("리모트 페어링 코드 발급(&P)", self)' not in source
    assert '/remote/pair/start' in source
    assert "class RemoteSettingsDialog" in dialog_source
    remote_dialog_source = dialog_source[
        dialog_source.index("class RemoteSettingsDialog"):
        dialog_source.index("class NumericTableWidgetItem")
    ]
    assert "remote_server_mode_checkbox" in dialog_source
    assert "QTabWidget" not in remote_dialog_source
    assert "_RemoteSettingsWorker" in dialog_source
    assert "_schedule_initial_refreshes" in remote_dialog_source
    assert "setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)" in remote_dialog_source
    assert "setMaximumHeight(150)" not in remote_dialog_source
    assert "ScrollBarAlwaysOff" in remote_dialog_source
    assert "_fit_devices_table_to_rows" in remote_dialog_source
    assert "Tailnet 기기" in remote_dialog_source
    assert "can_revoke" in remote_dialog_source
    assert "_start_worker(\"devices\"" in remote_dialog_source
    assert "_start_worker(\"tailscale\"" in remote_dialog_source
    assert "_start_worker(\"power\"" in remote_dialog_source
    assert "devices_table" in dialog_source
    assert "tailscale_health_text" in dialog_source
    assert "power_setup_text" in dialog_source
    assert "/remote/power/setup" in dialog_source
    assert "/remote/power/ssh-key" not in dialog_source
    assert "/remote/power/config" not in dialog_source
    assert "/remote/power/smartthings/devices" not in dialog_source
    assert "smartthings_device_id_edit" not in dialog_source
    assert "smartthings_device_combo" not in dialog_source
    assert "SSH public key 승인/등록" not in dialog_source
    assert "전원 설정 저장" not in dialog_source
    assert "호스트 전원 준비 상태" in dialog_source
    assert "클라이언트가 SmartThings/OpenSSH 직접 경로" in dialog_source


def test_resource_tracking_settings_dialog_uses_advanced_cookie_flows():
    source = Path("src/gui/dialogs.py").read_text(encoding="utf-8")
    dialog_source = source[source.index("class HoYoLabSettingsDialog"):]

    assert 'setWindowTitle("자원/출석 관리")' in dialog_source
    assert "QTabWidget" in source
    assert 'self.tabs.addTab(account_tab, "계정/토큰")' in dialog_source
    assert 'self.tabs.addTab(checkin_tab, "자동 출석")' in dialog_source
    assert 'self.tabs.addTab(logs_tab, "최근 로그")' in dialog_source
    assert "HoYoLabAdvancedCredentialsDialog" in source
    assert "NikkeAdvancedSessionDialog" in source
    assert "hoyolab_advanced_btn" in dialog_source
    assert "nikke_advanced_btn" in dialog_source
    assert "check_cookies_btn" in dialog_source
    assert "daily_checkin_table" in dialog_source
    assert "daily_checkin_logs_table" in dialog_source
    assert "지금 출석" in dialog_source
    assert "run_daily_checkin" in dialog_source
    assert "probe_daily_checkin_status" in dialog_source
    assert "set_daily_checkin_enabled" in dialog_source
    assert "get_provider_credential_health" in dialog_source
    assert "update_provider_credential_health" in dialog_source
    assert "유효성은 검사/자동 동기화 결과" in dialog_source
    assert "manual_cookie_check" in dialog_source
    assert "customContextMenuRequested" in dialog_source
    assert "메시지 복사" in dialog_source
    assert "로그 행 복사" in dialog_source
    assert "_copy_daily_checkin_log_message" in dialog_source
    assert "_daily_checkin_status_style" in dialog_source
    assert "hoyolab_checkin_run_btn" not in dialog_source
    assert "nikke_checkin_status_btn" not in dialog_source
    assert "cookie_check_status_label" in dialog_source
    assert "QDialogButtonBox.StandardButton.Close" in dialog_source
    assert "self.ltuid_edit" not in dialog_source
    assert "self.ltoken_edit" not in dialog_source
    assert "self.ltmid_edit" not in dialog_source
    assert "save_credentials(int(cookies.get(\"ltuid\"))" in dialog_source


def test_resource_tracking_dialog_maps_manual_blabla_token_error_to_provider_health():
    from src.core import credential_health
    import src.gui.dialogs as dialogs

    payload = dialogs.HoYoLabSettingsDialog._provider_health_payload_from_lines(
        credential_health.PROVIDER_NIKKE_BLABLALINK,
        [
            "✅ BlablaLink: 전초기지 방어 보상 42.0% (서버=1)",
            "❌ BlablaLink 출석: BlablaLink/NIKKE 로그인 또는 바인딩 상태 확인 필요 (ret=11002: Inner token is invalid[3].)",
        ],
        source="manual_cookie_check",
    )

    assert payload is not None
    assert payload["provider"] == credential_health.PROVIDER_NIKKE_BLABLALINK
    assert payload["status"] == credential_health.HEALTH_AUTH_PROBLEM
    assert payload["reason"] == "game_login_required"
    assert "Inner token is invalid[3]" in payload["message"]


def test_resource_tracking_dialog_does_not_overwrite_provider_health_on_network_error():
    from src.core import credential_health
    import src.gui.dialogs as dialogs

    payload = dialogs.HoYoLabSettingsDialog._provider_health_payload_from_lines(
        credential_health.PROVIDER_NIKKE_BLABLALINK,
        ["❌ BlablaLink 출석: 네트워크/API 요청 실패 (timeout)"],
        source="manual_cookie_check",
    )

    assert payload is None


def test_remote_settings_device_table_fits_rows_and_pairing_code_is_left_aligned(monkeypatch):
    app = _qapp()
    import src.gui.dialogs as dialogs

    monkeypatch.setattr(dialogs.RemoteSettingsDialog, "_schedule_initial_refreshes", lambda self: None)
    dialog = dialogs.RemoteSettingsDialog(_FakeApiClient([]))
    try:
        assert dialog.pairing_code_edit.alignment() & Qt.AlignmentFlag.AlignLeft
        assert dialog.devices_table.columnCount() == 8
        assert dialog.devices_table.isColumnHidden(0)
        assert dialog.devices_table.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        assert dialog.devices_table.maximumHeight() > 1000

        dialog._populate_devices([])
        empty_height = dialog.devices_table.height()
        dialog._populate_devices([
            {"id": f"device-{index}", "name": f"Device {index}", "platform": "macOS"}
            for index in range(4)
        ])
        app.processEvents()

        assert dialog.devices_table.rowCount() == 4
        assert dialog.devices_table.height() > empty_height
        assert dialog.devices_table.item(0, 0).data(Qt.ItemDataRole.UserRole) is True
        expected_min = (
            dialog.devices_table.horizontalHeader().height()
            + sum(dialog.devices_table.rowHeight(row) for row in range(dialog.devices_table.rowCount()))
            + dialog.devices_table.frameWidth() * 2
        )
        assert dialog.devices_table.height() >= expected_min

        dialog._populate_devices([
            {"id": "host:100.1.2.3", "name": "Host", "role": "host", "tailnet_ip": "100.1.2.3", "can_revoke": False}
        ])
        assert dialog.devices_table.item(0, 0).data(Qt.ItemDataRole.UserRole) is False
        assert dialog.devices_table.item(0, 5).text() == "-"
        assert dialog.devices_table.item(0, 6).text() == "-"
        assert not bool(dialog.devices_table.item(0, 0).flags() & Qt.ItemFlag.ItemIsSelectable)
        assert not bool(dialog.devices_table.item(0, 0).flags() & Qt.ItemFlag.ItemIsEnabled)

        dialog._populate_devices([
            {
                "id": "device-a",
                "name": "MacBook",
                "role": "client",
                "tailnet_ip": "100.114.138.46",
                "pairing_status": "paired",
                "connectivity_state": "stale_or_offline",
                "health_message": "debug detail",
                "can_revoke": True,
            }
        ])
        assert dialog.devices_table.item(0, 5).text() == "페어링됨"
        assert dialog.devices_table.item(0, 5).toolTip() == "paired"
        assert dialog.devices_table.item(0, 6).text() == "대기/오프라인"
        assert dialog.devices_table.item(0, 6).toolTip() == "debug detail"

        dialog._populate_devices([
            {"id": "tailnet:100.2.2.2", "name": "Zeta", "role": "unknown", "tailnet_ip": "100.2.2.2", "pairing_status": "tailnet_unpaired", "can_revoke": False},
            {"id": "device-b", "name": "Beta", "role": "client", "tailnet_ip": "100.1.1.2", "pairing_status": "paired", "can_revoke": True},
            {"id": "host:100.1.1.1", "name": "Host", "role": "host", "tailnet_ip": "100.1.1.1", "can_revoke": False},
            {"id": "device-a", "name": "Alpha", "role": "client", "tailnet_ip": "100.1.1.3", "pairing_status": "paired", "can_revoke": True},
        ])
        assert [dialog.devices_table.item(row, 2).text() for row in range(dialog.devices_table.rowCount())] == ["Host", "Alpha", "Beta", "Zeta"]
        assert dialog.devices_table.item(1, 0).data(Qt.ItemDataRole.UserRole) is True
        assert dialog.devices_table.item(3, 0).data(Qt.ItemDataRole.UserRole) is False
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_menu_bar_dropdown_actions_are_text_only(monkeypatch, tmp_path):
    app = _qapp()
    main_window = _patch_main_window_deps(monkeypatch, tmp_path)
    window = main_window.MainWindow(_FakeApiClient([]))
    try:
        dropdown_actions = []
        for top_level_action in window.menuBar().actions():
            menu = top_level_action.menu()
            if menu is not None:
                dropdown_actions.extend(action for action in menu.actions() if not action.isSeparator())

        assert dropdown_actions
        assert all(not action.isIconVisibleInMenu() for action in dropdown_actions)
    finally:
        _stop_window(window, app)


def test_main_window_uses_three_read_only_bottom_readiness_items():
    source = Path("src/gui/main_window.py").read_text(encoding="utf-8")

    assert "showMessage(" not in source
    assert 'setObjectName("readinessStrip")' in source
    assert "system_status_button" not in source
    assert 'for key in ("beholder", "remote", "admin")' in source
    assert "QGraphicsDropShadowEffect" not in source
    assert "QStatusBar" not in source


def test_bottom_readiness_items_show_compact_state_and_keep_details_in_tooltips(monkeypatch, tmp_path):
    app = _qapp()
    main_window = _patch_main_window_deps(monkeypatch, tmp_path)
    window = main_window.MainWindow(_FakeApiClient([]))
    try:
        window._set_remote_readiness_indicator("remote", "yellow", "원격 연결 확인 필요")
        remote_dot, remote_text = window._readiness_status_widgets["remote"]
        assert remote_dot.property("hhState") == "yellow"
        assert remote_text.text() == "원격 준비 중"
        assert remote_text.toolTip() == "원격 연결 확인 필요"

        window._set_remote_readiness_indicator("beholder", "red", "데이터 보호 오류")
        data_dot, data_text = window._readiness_status_widgets["beholder"]
        assert data_dot.property("hhState") == "red"
        assert data_text.text() == "데이터 오류"
        assert data_text.toolTip() == "데이터 보호 오류"
        assert all(not label.hasMouseTracking() for pair in window._readiness_status_widgets.values() for label in pair)
    finally:
        _stop_window(window, app)


def test_remote_server_mode_is_owned_by_remote_settings_dialog_only():
    dialog_source = Path("src/gui/dialogs.py").read_text(encoding="utf-8")
    launcher_source = Path("homework_helper.pyw").read_text(encoding="utf-8")
    global_dialog_source = dialog_source[
        dialog_source.index("class GlobalSettingsDialog"):
        dialog_source.index("class WebShortcutDialog")
    ]
    remote_dialog_source = dialog_source[
        dialog_source.index("class RemoteSettingsDialog"):
        dialog_source.index("class NumericTableWidgetItem")
    ]

    assert "remote_server_mode_checkbox" not in global_dialog_source
    assert "remote_server_mode_checkbox" in remote_dialog_source
    assert "updated.remote_server_mode_enabled = getattr(self.current_settings" in global_dialog_source
    assert "def resolve_api_bind_host" in launcher_source
    assert '"0.0.0.0"' in launcher_source
    assert "remote_server_mode_enabled" in launcher_source


def _stop_window(window, app):
    window._shutting_down = True
    window._timer_registry.shutdown()
    assert window.prepare_database_restore()
    # DeferredDelete is not dispatched by processEvents alone without an outer
    # event loop. Deliver it now so hidden windows cannot leak into the next test.
    if type(window).INSTANCE is window:
        type(window).INSTANCE = None
    window.hide()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(window, QEvent.Type.DeferredDelete)


@pytest.mark.parametrize("failure", ["scan", "api"])
def test_startup_retries_before_monitoring_and_preserves_previous_heartbeat(monkeypatch, tmp_path, failure):
    import time
    from src.api.client import BackgroundApiTransport, BackgroundHttpResult
    from src.core.process_monitor import ProcessScanSnapshot
    app = _qapp()
    main_window = _patch_main_window_deps(monkeypatch, tmp_path)
    observations, requests = [], []

    def detect(_targets, **_kwargs):
        observations.append("startup")
        if failure == "scan" and len(observations) == 1:
            raise OSError("isolated pipe unavailable")
        return set()

    def post(_self, path, _payload, **_kwargs):
        requests.append(path)
        if failure == "api" and requests.count("/api/beholder/open-sessions/reconcile") == 1:
            raise OSError("isolated API unavailable")
        return BackgroundHttpResult(status_code=200, elapsed_seconds=0, payload={"incidents": []})

    def scan(_targets, **_kwargs):
        observations.append("monitor")
        return ProcessScanSnapshot((), time.time())

    monkeypatch.setattr(main_window, "detect_running_process_ids", detect)
    monkeypatch.setattr(main_window, "scan_running_processes", scan)
    monkeypatch.setattr(BackgroundApiTransport, "post_json", post)
    window = main_window.MainWindow(_FakeApiClient([]))

    def pump(predicate):
        deadline = time.monotonic() + 2.0
        while not predicate() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.002)
        assert predicate()

    try:
        window._reconcile_open_sessions_after_startup()
        pump(lambda: window._api_backoff_failures.get("startup_reconcile") == 1)
        window._send_runtime_heartbeat()
        window.run_process_monitor_check()  # Also covers a wake callback during startup.
        assert "monitor" not in observations
        assert "/api/beholder/runtime/heartbeat" not in requests
        assert window.startup_reconcile_timer.isActive()
        assert not window.monitor_timer.isActive()
        window._api_backoff_until["startup_reconcile"] = 0
        window.startup_reconcile_timer.timeout.emit()
        pump(lambda: window.monitor_timer.isActive() and "monitor" in observations
             and "/api/beholder/runtime/heartbeat" in requests)
        assert not window.startup_reconcile_timer.isActive()
        previous = requests.count("/api/beholder/open-sessions/reconcile")
        window._timer_registry.restart_desired()
        window._reconcile_open_sessions_after_startup()
        assert not window.startup_reconcile_timer.isActive()
        assert requests.count("/api/beholder/open-sessions/reconcile") == previous
    finally:
        _stop_window(window, app)


def test_main_window_launch_args_apply_only_to_direct_targets():
    import src.gui.main_window as main_window

    process = ManagedProcess(
        id="zzz",
        name="Zenless Zone Zero",
        monitoring_path="/Games/ZZZ.exe",
        launch_path="/Games/ZZZ.url",
        preferred_launch_type="direct",
        launch_args_enabled=True,
        launch_args="  -use-d3d12  ",
    )
    probe = SimpleNamespace()

    assert main_window.MainWindow._launch_args_for_process(
        probe,
        process,
        "direct",
        "/Games/ZZZ.exe",
    ) == "-use-d3d12"
    assert main_window.MainWindow._launch_args_for_process(
        probe,
        process,
        "shortcut",
        "/Games/ZZZ.exe",
    ) == "-use-d3d12"
    assert main_window.MainWindow._launch_args_for_process(
        probe,
        process,
        "launcher",
        "/Games/ZZZ.exe",
    ) is None
    assert main_window.MainWindow._launch_args_for_process(
        probe,
        process,
        "direct",
        "/Games/ZZZ.url",
    ) is None


def test_process_dialog_returns_launch_args_opt_in(monkeypatch, tmp_path):
    app = _qapp()
    import src.gui.dialogs as dialogs
    from src.utils.game_preset_manager import GamePresetManager

    monkeypatch.setattr(GamePresetManager, "USER_CONFIG_DIR", tmp_path / "HomeworkHelper", raising=False)
    monkeypatch.setattr(
        GamePresetManager,
        "USER_PRESET_FILE",
        tmp_path / "HomeworkHelper" / "game_presets_user.json",
        raising=False,
    )

    dialog = dialogs.ProcessDialog()
    try:
        dialog.name_edit.setText("Zenless Zone Zero")
        dialog.monitoring_path_edit.setText("/Games/ZZZ.exe")
        dialog.launch_path_edit.setText("/Games/ZZZ.url")
        direct_index = dialog.launch_type_combo.findData("direct")
        dialog.launch_type_combo.setCurrentIndex(direct_index)
        dialog.launch_args_enabled_checkbox.setChecked(True)
        dialog.launch_args_edit.setText("  -use-d3d12  ")

        data = dialog.get_data()

        assert data is not None
        assert data["preferred_launch_type"] == "direct"
        assert data["launch_args_enabled"] is True
        assert data["launch_args"] == "-use-d3d12"
        assert dialog.launch_args_edit.isEnabled() is True
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_main_game_table_restores_name_sort_and_centered_icons(monkeypatch, tmp_path):
    app = _qapp()
    main_window = _patch_main_window_deps(monkeypatch, tmp_path)
    icon_requests = []
    monkeypatch.setattr(
        main_window,
        "get_qicon_for_file",
        lambda path, *, icon_size=24, process_id=None: icon_requests.append((path, icon_size, process_id)) or QIcon(),
    )
    processes = [
        ManagedProcess(id="z", name="Zeta", monitoring_path="z.exe", launch_path="z.exe"),
        ManagedProcess(id="a", name="Alpha", monitoring_path="a.exe", launch_path="a.exe"),
        ManagedProcess(id="b", name="Beta", monitoring_path="b.exe", launch_path="b.exe"),
    ]
    window = main_window.MainWindow(_FakeApiClient(processes))
    try:
        window.show()
        app.processEvents()
        window._adjust_window_size_to_content()
        app.processEvents()

        assert not window.process_table.horizontalHeader().isVisible()
        assert not window.process_table.verticalHeader().isVisible()
        assert not window.process_table.isSortingEnabled()
        assert [
            window.process_table.item(row, window.COL_NAME).text()
            for row in range(window.process_table.rowCount())
        ] == ["Alpha", "Beta", "Zeta"]
        assert [request[2] for request in icon_requests] == ["a", "b", "z"]
        assert {request[1] for request in icon_requests} == {window._TABLE_ICON_LOGICAL_SIZE}
        icon_cell = window.process_table.cellWidget(0, window.COL_ICON)
        assert isinstance(icon_cell, QLabel)
        assert icon_cell.alignment() & Qt.AlignmentFlag.AlignHCenter
        assert icon_cell.alignment() & Qt.AlignmentFlag.AlignVCenter
        assert window.process_table.columnWidth(window.COL_ICON) <= (
            window._TABLE_ICON_LOGICAL_SIZE + window._TABLE_ICON_COLUMN_PADDING
        )
        assert all(
            window.process_table.rowHeight(row) == window._TABLE_ROW_HEIGHT
            for row in range(window.process_table.rowCount())
        )
        launch_cell = window.process_table.cellWidget(0, window.COL_LAUNCH_BTN)
        launch_button = launch_cell.findChild(QPushButton)
        assert launch_button is not None
        assert launch_button.height() == window._TABLE_LAUNCH_BUTTON_HEIGHT
    finally:
        _stop_window(window, app)


@pytest.mark.parametrize("process_count", [0, 1, 2, 3, 4, 8])
def test_main_table_window_fits_all_rows_without_scroll(monkeypatch, tmp_path, process_count):
    app = _qapp()
    main_window = _patch_main_window_deps(monkeypatch, tmp_path)
    processes = [
        ManagedProcess(
            id=f"game-{index}",
            name=f"Game {index + 1}",
            monitoring_path=f"game-{index}.exe",
            launch_path=f"game-{index}.exe",
        )
        for index in range(process_count)
    ]
    window = main_window.MainWindow(_FakeApiClient(processes))
    try:
        window.show()
        app.processEvents()
        window._adjust_window_size_to_content()
        app.processEvents()

        assert window.process_table.rowCount() == process_count
        assert window.process_table.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        assert window.process_table.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        assert window.minimumSize() == window.size()
        assert window.maximumSize() == window.size()
        assert window.size() == window.sizeHint().expandedTo(
            QSize(window._MIN_WINDOW_WIDTH, window._MIN_WINDOW_HEIGHT)
        )
        expected_height = window.process_table.frameWidth() * 2 + sum(
            window.process_table.rowHeight(row)
            for row in range(window.process_table.rowCount())
        )
        if process_count == 0:
            expected_height += window._TABLE_ROW_HEIGHT
        assert window.process_table.height() == expected_height
        assert window.top_button_area.width() == window.process_table.width()
        assert window.readiness_strip.width() == window.process_table.width()
    finally:
        _stop_window(window, app)


def test_restore_window_state_reapplies_content_fixed_size(monkeypatch, tmp_path):
    app = _qapp()
    main_window = _patch_main_window_deps(monkeypatch, tmp_path)
    window = main_window.MainWindow(
        _FakeApiClient([
            ManagedProcess(id="a", name="Alpha", monitoring_path="a.exe", launch_path="a.exe"),
        ])
    )
    try:
        window.show()
        app.processEvents()
        window._restore_window_state()
        app.processEvents()

        assert window.minimumSize() == window.size()
        assert window.maximumSize() == window.size()
    finally:
        _stop_window(window, app)


@pytest.mark.parametrize("state", ["visible", "minimized", "hidden"])
@pytest.mark.parametrize("entry", ["tray", "ipc"])
def test_explicit_quit_returns_gui_loop_and_stops_owned_child(tmp_path, state, entry):
    # QApplication.exit must run inside exec(), in a separate process so it
    # cannot quit pytest's shared QApplication. The real entrypoint is compiled
    # without importing its production DB/server initialization.
    code = textwrap.dedent('''
        import ast, atexit, json, multiprocessing, os, signal, sys
        from pathlib import Path
        from types import SimpleNamespace
        import pytest
        from PySide6.QtCore import QSettings, QTimer
        from PySide6.QtGui import QAction, QFont, QFontDatabase
        from PySide6.QtNetwork import QLocalSocket
        from PySide6.QtWidgets import QApplication
        from test_gui_layout import _FakeApiClient, _patch_main_window_deps
        from test_api_runtime_stability import _load_stop_api_server_contract
        from src.core.instance_manager import SingleInstanceApplication, InstanceCommand, encode_instance_command
        from src.gui import tray_manager as tray

        root, state, entry = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(root / 'qt-settings'))
        mp = pytest.MonkeyPatch()
        module = _patch_main_window_deps(mp, root)
        mp.setattr(module.MainWindow, '_set_gamebar_capture', lambda self, enabled: None)
        mp.setattr(module.MainWindow, '_restore_gamebar_setting', lambda self: None)
        mp.setattr(tray.TrayManager, '_setup_tray_icon_and_menu', lambda self: None)
        mp.setattr(tray, 'is_windows', lambda: True)
        mp.setattr(module, 'is_windows', lambda: True)
        mp.setattr(tray, 'set_windows_taskbar_visible', lambda *_: True)
        mp.setattr(module, 'set_windows_taskbar_visible', lambda *_: True)
        context = multiprocessing.get_context('spawn')
        shutdown = context.Event()
        child = context.Process(target=shutdown.wait, args=(10,), daemon=False)
        child.start()
        child.terminate = child.kill = lambda: (_ for _ in ()).throw(AssertionError('forced child termination'))
        manager = SingleInstanceApplication('Isolated Quit', executable_path=root / 'isolated-host.exe')
        namespace = _load_stop_api_server_contract()
        namespace.update(os=os, api_server_process=child, api_server_shutdown_event=shutdown,
                         _server_pid_file_path=lambda: str(root / 'server.pid'),
                         _server_metadata_file_path=lambda: str(root / 'server.json'))
        stop_owned_child = namespace['stop_api_server']
        observed = []
        clients = []
        def stop_api():
            observed.append('api_stop_after_gui_loop')
            return stop_owned_child(timeout=3.0)
        def create_window(client, instance_manager):
            window = module.MainWindow(client, instance_manager=instance_manager)
            window.tray_manager = tray.TrayManager(window)
            window.tray_manager.tray_icon = SimpleNamespace(hide=lambda: None, isVisible=lambda: True)
            action = QAction('종료', window)
            action.triggered.connect(window.initiate_quit_sequence)
            def request_quit():
                if state == 'minimized':
                    window.tray_manager.hide_window_to_tray('test')
                elif state == 'hidden':
                    window.hide()
                if entry == 'tray':
                    action.trigger()
                else:
                    socket = QLocalSocket()
                    clients.append(socket)
                    socket.connectToServer(manager._identity.server_name)
                    assert socket.waitForConnected(500)
                    socket.write(encode_instance_command(InstanceCommand.QUIT_APPLICATION, manager._identity))
                    socket.flush()
            QTimer.singleShot(0, request_quit)
            QTimer.singleShot(1000, lambda: QApplication.instance().exit(77))
            return window
        namespace.update(__name__='isolated_gui_entrypoint', sys=sys, atexit=atexit, signal=signal,
                         QApplication=QApplication, QFont=QFont, QFontDatabase=QFontDatabase,
                         SingleInstanceApplication=SingleInstanceApplication, is_admin=lambda: False,
                         get_bundle_resource_path=lambda _: str(root / 'absent-font'),
                         binding_diagnostics=lambda: {}, _prepare_gui_database=lambda _: True,
                         ApiClient=lambda: _FakeApiClient([]), MainWindow=create_window, stop_api_server=stop_api)
        tree = ast.parse(Path('homework_helper.pyw').read_text(encoding='utf-8'))
        node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'start_main_application')
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), 'homework_helper.pyw', 'exec'), namespace)
        try:
            namespace['start_main_application'](manager)
        except SystemExit as result:
            print('QUIT_RESULT ' + json.dumps({'loop_exit': result.code, 'api_stopped': not child.is_alive(),
                                              'shutdown_signalled': shutdown.is_set(), 'observed': observed}))
        finally:
            shutdown.set()
            child.join(3.0)
    ''')
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", APPDATA=str(tmp_path),
               LOCALAPPDATA=str(tmp_path), HH_TEST_APPDATA_DIR=str(tmp_path),
               PYTHONPATH=os.pathsep.join((str(Path("tests").resolve()), str(Path.cwd()))))
    if os.name != "nt":
        # macOS's pytest temp path plus the socket name exceeds AF_UNIX's
        # path limit. QLocalServer already uses a unique executable digest.
        env["TMPDIR"] = "/tmp"
    result = subprocess.run([sys.executable, "-c", code, str(tmp_path), state, entry],
                            env=env, text=True, encoding="utf-8", capture_output=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = next(line.removeprefix("QUIT_RESULT ") for line in result.stdout.splitlines()
                   if line.startswith("QUIT_RESULT "))
    assert json.loads(payload) == {
        "loop_exit": 0, "api_stopped": True, "shutdown_signalled": True,
        "observed": ["api_stop_after_gui_loop"],
    }


@pytest.mark.parametrize("entry", ["tray", "game", "minimize", "close"])
def test_main_tray_hiding_preserves_native_minimized_window_and_shared_restore(monkeypatch, tmp_path, entry):
    from PySide6.QtWidgets import QSystemTrayIcon
    from src.gui import tray_manager as tray_module
    from src.gui.gui_notification_handler import GuiNotificationHandler
    app = _qapp()
    module = _patch_main_window_deps(monkeypatch, tmp_path)
    monkeypatch.setattr(tray_module.TrayManager, "_setup_tray_icon_and_menu", lambda self: None)
    monkeypatch.setattr(tray_module, "is_windows", lambda: True)
    monkeypatch.setattr(module, "is_windows", lambda: True)
    calls = []
    def taskbar(hwnd, visible):
        calls.append(visible)
        return True
    monkeypatch.setattr(tray_module, "set_windows_taskbar_visible", taskbar)
    monkeypatch.setattr(module, "set_windows_taskbar_visible", taskbar)
    window = module.MainWindow(_FakeApiClient([]))
    manager = tray_module.TrayManager(window)
    manager.tray_icon = SimpleNamespace(isVisible=lambda: True, hide=lambda: None)
    window.tray_manager = manager
    try:
        window.show()
        app.processEvents()
        if entry == "tray":
            manager._handle_tray_icon_activation(QSystemTrayIcon.ActivationReason.Trigger)
        elif entry == "game":
            window._hide_main_window_to_tray("game_started")
        elif entry == "minimize":
            window.showMinimized()
        else:
            window.close()
        app.processEvents()
        assert window.isMinimized() and window.isVisible() and not window.isHidden()
        assert calls == [False]
        assert not app.quitOnLastWindowClosed()
        if entry == "tray":
            manager._handle_tray_icon_activation(QSystemTrayIcon.ActivationReason.Trigger)
        elif entry == "game":
            GuiNotificationHandler(window).process_system_notification_activation(None)
        else:
            window.activate_and_show()
        app.processEvents()
        assert window.isVisible() and not window.isMinimized()
        assert calls == [False, True]
    finally:
        _stop_window(window, app)


@pytest.mark.parametrize("visible", [True, False])
def test_native_taskbar_visibility_uses_shell_without_hiding_window(monkeypatch, visible):
    import sys
    from src.utils import windows
    calls = []
    taskbar = SimpleNamespace(HrInit=lambda: calls.append("init"),
                              AddTab=lambda hwnd: calls.append(("add", hwnd)),
                              DeleteTab=lambda hwnd: calls.append(("delete", hwnd)))
    def create(*args):
        calls.append(("create", args))
        return taskbar
    monkeypatch.setattr(windows, "is_windows", lambda: True)
    monkeypatch.setitem(sys.modules, "pythoncom", SimpleNamespace(CoCreateInstance=create, CLSCTX_INPROC_SERVER=1))
    shell = SimpleNamespace(CLSID_TaskbarList="TaskbarList", IID_ITaskbarList="ITaskbarList")
    monkeypatch.setitem(sys.modules, "win32com.shell", SimpleNamespace(shell=shell))
    assert windows.set_windows_taskbar_visible(123, visible)
    assert calls == [("create", ("TaskbarList", None, 1, "ITaskbarList")), "init",
                     ("add" if visible else "delete", 123)]


def test_native_taskbar_failure_is_reported_without_window_fallback(monkeypatch, caplog):
    import sys
    from src.utils import windows
    def failed(*_args):
        raise OSError("synthetic Shell failure")
    monkeypatch.setattr(windows, "is_windows", lambda: True)
    monkeypatch.setitem(sys.modules, "pythoncom", SimpleNamespace(CoCreateInstance=failed, CLSCTX_INPROC_SERVER=1))
    shell = SimpleNamespace(CLSID_TaskbarList="TaskbarList", IID_ITaskbarList="ITaskbarList")
    monkeypatch.setitem(sys.modules, "win32com.shell", SimpleNamespace(shell=shell))
    assert not windows.set_windows_taskbar_visible(123, False)
    assert "Windows 작업 표시줄 버튼 변경 실패" in caplog.text


def test_main_restore_has_no_visible_scrollbar_or_reserved_right_strip(monkeypatch, tmp_path):
    from PySide6.QtWidgets import QScrollBar
    app = _qapp()
    module = _patch_main_window_deps(monkeypatch, tmp_path)
    names = ["명조: 위더링 웨이브", "몬길: STAR DIVE", "붕괴: 스타레일", "붕괴: 스타레일(베타)",
             "소녀전선2: 망명", "승리의 여신: 니케", "젠레스 존 제로"]
    data = _FakeApiClient([ManagedProcess(id=str(i), name=name, monitoring_path=f"/test/{i}.exe",
                                        launch_path=f"/test/{i}.exe") for i, name in enumerate(names)])
    data.global_settings.theme = "dark"
    window = module.MainWindow(data)
    try:
        window.show()
        app.processEvents()
        window.hide()
        window.activate_and_show()
        app.processEvents()
        table = window.process_table
        assert all(not bar.isVisible() for bar in window.findChildren(QScrollBar))
        assert table.viewport().width() == table.contentsRect().width()
        assert table.viewport().height() == table.contentsRect().height()
        image = window.grab().toImage()
        start = window.menuBar().height() + 1
        assert all(image.pixelColor(image.width() - 1, y).lightness() < 80
                   for y in range(start, image.height() - 1))
    finally:
        _stop_window(window, app)


def test_dashboard_button_uses_original_chart_glyph(monkeypatch, tmp_path):
    app = _qapp()
    main_window = _patch_main_window_deps(monkeypatch, tmp_path)
    window = main_window.MainWindow(_FakeApiClient([]))
    try:
        assert window.dashboard_button.text() == "📊"
        assert window.dashboard_button.icon().isNull()
        assert window.dashboard_button.size() == window.add_web_shortcut_button.size()
        assert window.dashboard_button.size().toTuple() == (30, 30)
        assert window.dashboard_button.size() == window.dashboard_button.sizeHint()
    finally:
        _stop_window(window, app)


def test_style_controlled_main_buttons_are_not_smaller_than_size_hints(monkeypatch, tmp_path):
    app = _qapp()
    main_window = _patch_main_window_deps(monkeypatch, tmp_path)
    process = ManagedProcess(id="game", name="Game", monitoring_path="game.exe", launch_path="game.exe")
    window = main_window.MainWindow(_FakeApiClient([process]))
    try:
        window.show()
        app.processEvents()
        buttons = window.findChildren(QPushButton)

        assert buttons
        assert all(
            button.width() >= button.sizeHint().width()
            and button.height() >= button.sizeHint().height()
            for button in buttons
        )
    finally:
        _stop_window(window, app)


def test_web_button_and_theme_changes_refit_through_same_fixed_size_path(monkeypatch, tmp_path):
    app = _qapp()
    main_window = _patch_main_window_deps(monkeypatch, tmp_path)
    client = _FakeApiClient([
        ManagedProcess(id="a", name="Alpha", monitoring_path="a.exe", launch_path="a.exe"),
    ])
    window = main_window.MainWindow(client)
    try:
        window.show()
        app.processEvents()
        initial_size = window.size()

        client.web_shortcuts = [
            WebShortcut(id=f"web-{index}", name=f"주요 서비스 바로가기 {index + 1}", url="https://example.com")
            for index in range(5)
        ]
        window._load_and_display_web_buttons()
        app.processEvents()
        assert window.width() > initial_size.width()
        assert window.minimumSize() == window.maximumSize() == window.size()

        window._apply_theme("dark")
        app.processEvents()
        assert window.minimumSize() == window.maximumSize() == window.size()

        client.web_shortcuts = []
        window._load_and_display_web_buttons()
        app.processEvents()
        assert window.width() == initial_size.width()
        assert window.minimumSize() == window.maximumSize() == window.size()
    finally:
        _stop_window(window, app)


def test_main_window_position_is_not_persisted_when_show_always_reanchors():
    source = Path("src/gui/main_window.py").read_text(encoding="utf-8")

    assert 'setValue("window_geometry"' not in source
    assert "restoreGeometry(" not in source
    assert "_position_on_cursor_screen_bottom_right" in source
    assert "position_windows_window_in_work_area(" in source
    assert "_pending_bottom_right_placement" in source
    assert "def moveEvent(self, event):" in source
    assert "self._position_window_in_work_area()" in source
    assert "_WindowsMovingEventFilter" not in source
    assert "QAbstractNativeEventFilter" not in source
    assert "QApplication.screenAt(QCursor.pos())" in source


def test_web_shortcut_click_uses_runtime_marker(monkeypatch, tmp_path):
    app = _qapp()
    main_window = _patch_main_window_deps(monkeypatch, tmp_path)
    shortcut = WebShortcut(
        id="daily",
        name="Daily",
        url="https://example.test",
        refresh_time_str="05:00",
    )
    data_manager = _FakeApiClient([])
    data_manager.web_shortcuts = [shortcut]
    marked = []

    def mark_opened(shortcut_id):
        marked.append(shortcut_id)
        shortcut.last_reset_timestamp = 1778410000.0
        return True

    data_manager.mark_web_shortcut_opened = mark_opened
    window = main_window.MainWindow(data_manager)
    opened = []
    window.open_webpage = lambda url: opened.append(url)
    try:
        window._handle_web_button_clicked(shortcut.id, shortcut.url)

        assert opened == [shortcut.url]
        assert marked == [shortcut.id]
    finally:
        _stop_window(window, app)


def test_dashboard_button_uses_data_manager_base_url(monkeypatch, tmp_path):
    app = _qapp()
    main_window = _patch_main_window_deps(monkeypatch, tmp_path)
    data_manager = _FakeApiClient([])
    data_manager.base_url = "http://127.0.0.1:43210"
    window = main_window.MainWindow(data_manager)
    opened = []
    window.open_webpage = lambda url: opened.append(url)
    try:
        window._open_dashboard()

        assert opened == ["http://127.0.0.1:43210/dashboard"]
    finally:
        _stop_window(window, app)


def test_resource_icon_label_centers_pixmap_in_fixed_space(monkeypatch, tmp_path):
    app = _qapp()
    main_window = _patch_main_window_deps(monkeypatch, tmp_path)
    window = main_window.MainWindow(_FakeApiClient([]))
    icon_path = tmp_path / "resource.png"
    pixmap = QPixmap(16, 16)
    pixmap.fill(QColor("#5cc8ff"))
    assert pixmap.save(str(icon_path))
    try:
        label = window._create_centered_resource_icon_label(str(icon_path))

        assert label.width() == 18
        assert label.height() == 18
        assert label.alignment() & Qt.AlignmentFlag.AlignHCenter
        assert label.alignment() & Qt.AlignmentFlag.AlignVCenter
        assert label.pixmap() is not None
        assert label.pixmap().width() <= 16
        assert label.pixmap().height() <= 16
    finally:
        _stop_window(window, app)


def test_progress_cell_uses_full_width_bar_and_only_real_resource_icon(monkeypatch, tmp_path):
    app = _qapp()
    main_window = _patch_main_window_deps(monkeypatch, tmp_path)
    process = ManagedProcess(id="a", name="Alpha", monitoring_path="a.exe", launch_path="a.exe")
    window = main_window.MainWindow(_FakeApiClient([process]))
    icon_path = tmp_path / "resource.png"
    pixmap = QPixmap(16, 16)
    pixmap.fill(QColor("#5cc8ff"))
    assert pixmap.save(str(icon_path))
    without_icon = None
    with_icon = None
    try:
        monkeypatch.setattr(window, "_get_stamina_icon_path", lambda _process: None)
        without_icon = window._create_progress_bar_widget(process, 50.0, "50분")
        without_icon.resize(240, window._TABLE_ROW_HEIGHT)
        without_icon.show()
        app.processEvents()
        assert len(without_icon.findChildren(QLabel)) == 1
        assert without_icon.findChild(QLabel, "progressText").alignment() & Qt.AlignmentFlag.AlignRight
        assert without_icon.findChild(QProgressBar).width() == without_icon.contentsRect().width()

        monkeypatch.setattr(window, "_get_stamina_icon_path", lambda _process: str(icon_path))
        with_icon = window._create_progress_bar_widget(process, 50.0, "50분")
        with_icon.resize(240, window._TABLE_ROW_HEIGHT)
        with_icon.show()
        app.processEvents()
        assert len(with_icon.findChildren(QLabel)) == 2
        labels = with_icon.findChildren(QLabel)
        resource_icon = next(label for label in labels if label.objectName() != "progressText")
        progress_text = with_icon.findChild(QLabel, "progressText")
        assert resource_icon.geometry().left() == with_icon.contentsRect().left()
        assert progress_text.geometry().right() == with_icon.contentsRect().right()
        assert resource_icon.geometry().right() < progress_text.geometry().left()
    finally:
        if without_icon is not None:
            without_icon.close()
        if with_icon is not None:
            with_icon.close()
        _stop_window(window, app)


def test_always_on_top_corner_has_safe_margin_and_right_alignment(monkeypatch, tmp_path):
    app = _qapp()
    main_window = _patch_main_window_deps(monkeypatch, tmp_path)
    window = main_window.MainWindow(_FakeApiClient([]))
    try:
        window.show()
        app.processEvents()
        margins = window._menu_corner_layout.contentsMargins()
        assert margins.left() == 0
        assert margins.top() == margins.bottom() == 0
        assert margins.right() == 0
        assert window._menu_corner_layout.count() == 2
        assert window._menu_corner_layout.itemAt(0).widget() is window._always_on_top_cb
        assert window._menu_corner_layout.itemAt(1).widget() is window._volume_btn
        menu_rect = window.menuBar().contentsRect()
        corner_rect = window._menu_corner_container.geometry()
        action_rect = window.menuBar().actionGeometry(window.menuBar().actions()[0])
        checkbox_rect = window._always_on_top_cb.geometry().translated(corner_rect.topLeft())
        volume_rect = window._volume_btn.geometry().translated(corner_rect.topLeft())
        # QMenuBar 자체의 4px 오른쪽 스타일 여백만 남고 별도 stretch는 없습니다.
        assert 0 <= menu_rect.right() - corner_rect.right() <= 4
        assert menu_rect.contains(corner_rect)
        assert checkbox_rect.center().y() == action_rect.center().y()
        assert volume_rect.center().y() == action_rect.center().y()
        assert window._always_on_top_cb.width() >= window._always_on_top_cb.sizeHint().width()
        assert checkbox_rect.right() + window._menu_corner_layout.spacing() < volume_rect.left()

        option = QStyleOptionButton()
        window._always_on_top_cb.initStyleOption(option)
        indicator_rect = window._always_on_top_cb.style().subElementRect(
            QStyle.SubElement.SE_CheckBoxIndicator,
            option,
            window._always_on_top_cb,
        )
        assert indicator_rect.top() > 0
        assert indicator_rect.bottom() < window._always_on_top_cb.height() - 1
    finally:
        _stop_window(window, app)


def test_volume_button_icon_uses_theme_text_color(monkeypatch, tmp_path):
    app = _qapp()
    main_window = _patch_main_window_deps(monkeypatch, tmp_path)
    window = main_window.MainWindow(_FakeApiClient([]))
    try:
        window._apply_theme("dark")
        app.processEvents()
        image = window._volume_btn.icon().pixmap(16, 16).toImage()
        visible_colors = [
            image.pixelColor(x, y)
            for y in range(image.height())
            for x in range(image.width())
            if image.pixelColor(x, y).alpha() > 0
        ]

        assert visible_colors
        assert all(color.lightness() > 200 for color in visible_colors)
    finally:
        _stop_window(window, app)


def test_main_window_starts_in_corner_but_preserves_user_move_and_content_resize(monkeypatch, tmp_path):
    app = _qapp()
    main_window = _patch_main_window_deps(monkeypatch, tmp_path)
    monkeypatch.setattr(main_window, "position_windows_window_in_work_area", lambda *_args, **_kwargs: False)
    client = _FakeApiClient([])
    window = main_window.MainWindow(client)
    try:
        # A generous work area permits resizing without containment correction.
        area = QRect(0, 0, 1800, 1000)
        screen = SimpleNamespace(geometry=lambda: area, availableGeometry=lambda: area)
        monkeypatch.setattr(window, "screen", lambda: screen)
        monkeypatch.setattr(main_window.QApplication, "screenAt", lambda _point: screen)
        window.show()
        for _ in range(3):
            app.processEvents()  # Finish initial fitting and its queued first placement.
        assert window.frameGeometry().bottomRight() == area.bottomRight()
        window.move(QPoint(150, 150))
        app.processEvents()
        user_position = window.frameGeometry().topLeft()
        assert user_position == QPoint(150, 150)
        window._on_ui_refresh_tick()
        app.processEvents()
        assert window.frameGeometry().topLeft() == user_position
        initial = window.size()
        client.web_shortcuts = [WebShortcut(id="wide", name="W" * 40, url="https://example.com")]
        window._load_and_display_web_buttons()
        app.processEvents()  # apply the content fit
        app.processEvents()  # apply its queued native/frame placement
        assert window.size() != initial
        assert window.frameGeometry().topLeft() == user_position
        client.web_shortcuts = []
        window._load_and_display_web_buttons()
        app.processEvents()  # apply the content fit
        app.processEvents()  # apply its queued native/frame placement
        assert window.size() == initial
        assert window.frameGeometry().topLeft() == user_position
        # All show entrypoints restore the corner policy, without storing geometry.
        window.hide()
        window.activate_and_show()
        for _ in range(3):
            app.processEvents()
        assert window.frameGeometry().bottomRight() == area.bottomRight()
        window.move(user_position)
        window.showMinimized()
        app.processEvents()
        window.activate_and_show()
        for _ in range(3):
            app.processEvents()
        assert window.frameGeometry().bottomRight() == area.bottomRight()
    finally:
        _stop_window(window, app)


def test_main_window_refresh_uses_monitor_origin_and_does_not_show_hidden_window(monkeypatch, tmp_path):
    app = _qapp()
    main_window = _patch_main_window_deps(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(main_window, "position_windows_window_in_work_area",
                        lambda hwnd, origin, **_kwargs: calls.append((hwnd, origin)) or True)
    window = main_window.MainWindow(_FakeApiClient([]))
    try:
        window.show()
        app.processEvents()
        calls.clear()
        window._on_ui_refresh_tick()
        origin = window.screen().geometry().topLeft()
        assert calls == [(int(window.winId()), (origin.x(), origin.y()))]
        changed = SimpleNamespace(geometry=lambda: QRect(-2560, 200, 1280, 720))
        window._position_window_in_work_area(changed)
        assert calls[-1] == (int(window.winId()), (-2560, 200))
        window.hide()
        app.processEvents()
        calls.clear()
        window._on_ui_refresh_tick()
        window._position_window_in_work_area(changed)
        assert calls == []
        assert not window.isVisible()
    finally:
        _stop_window(window, app)


def test_main_window_existing_refresh_contains_taskbar_overlap_without_forcing_corner(monkeypatch, tmp_path):
    app = _qapp()
    main_window = _patch_main_window_deps(monkeypatch, tmp_path)
    monkeypatch.setattr(main_window, "position_windows_window_in_work_area", lambda *_args, **_kwargs: False)
    window = main_window.MainWindow(_FakeApiClient([]))
    try:
        window.show()
        for _ in range(3):
            app.processEvents()
        geometry = window.screen().geometry()
        work = QRect(geometry)
        screen = SimpleNamespace(geometry=lambda: geometry, availableGeometry=lambda: work)
        monkeypatch.setattr(window, "screen", lambda: screen)
        window._position_window_in_work_area(placement="bottom_right")
        work.setHeight(geometry.height() - 48)
        window._on_ui_refresh_tick()
        assert window.frameGeometry().bottomRight() == work.bottomRight()
        contained = window.frameGeometry().topLeft()
        work.setHeight(geometry.height())
        window._on_ui_refresh_tick()
        assert window.frameGeometry().topLeft() == contained
        work.setHeight(geometry.height() - 48)
        window._on_ui_refresh_tick()
        assert window.frameGeometry().bottomRight() == work.bottomRight()
    finally:
        _stop_window(window, app)


@pytest.mark.parametrize("edge", ["left", "top", "right", "bottom"])
def test_main_window_drag_snaps_near_each_edge_and_can_move_away(monkeypatch, tmp_path, edge):
    app = _qapp()
    main_window = _patch_main_window_deps(monkeypatch, tmp_path)
    monkeypatch.setattr(main_window, "position_windows_window_in_work_area", lambda *_args, **_kwargs: False)
    window = main_window.MainWindow(_FakeApiClient([]))
    area = QRect(0, 0, 1600, 1000)
    screen = SimpleNamespace(geometry=lambda: area, availableGeometry=lambda: area)
    monkeypatch.setattr(window, "screen", lambda: screen)
    monkeypatch.setattr(main_window.QApplication, "screenAt", lambda _point: screen)
    try:
        window.show()
        for _ in range(3):
            app.processEvents()
        frame = window.frameGeometry()
        center_x, center_y = 400, 400
        target = {
            "left": QPoint(area.left() + 10, center_y),
            "top": QPoint(center_x, area.top() + 10),
            "right": QPoint(area.right() - frame.width() + 1 - 10, center_y),
            "bottom": QPoint(center_x, area.bottom() - frame.height() + 1 - 10),
        }[edge]
        window.move(target)
        app.processEvents()
        frame = window.frameGeometry()
        assert getattr(frame, edge)() == getattr(area, edge)()
        if edge in {"left", "right"}:
            assert frame.top() == center_y
        else:
            assert frame.left() == center_x
        # Leaving the edge is a normal move; later refresh must preserve it.
        window.move(QPoint(center_x, center_y))
        app.processEvents()
        window._on_ui_refresh_tick()
        assert window.frameGeometry().topLeft() == QPoint(center_x, center_y)
    finally:
        _stop_window(window, app)


@pytest.mark.parametrize("rect, work, placement, expected", [
    ((100, 200, 500, 600), (0, 0, 1920, 1080), "snap", (100, 200, 500, 600)),
    ((15, 100, 415, 500), (0, 0, 1920, 1080), "snap", (0, 100, 400, 500)),
    ((16, 100, 416, 500), (0, 0, 1920, 1080), "snap", (16, 100, 416, 500)),
    ((100, 15, 500, 415), (0, 0, 1920, 1080), "snap", (100, 0, 500, 400)),
    ((1510, 500, 1910, 1070), (0, 0, 1920, 1080), "snap", (1520, 510, 1920, 1080)),
    ((1510, 500, 1910, 1070), (0, 0, 1920, 1080), "contain", (1510, 500, 1910, 1070)),
    ((500, 800, 1200, 1300), (0, 0, 1920, 1080), "contain", (500, 580, 1200, 1080)),
    ((-20, -30, 480, 370), (0, 0, 1920, 1080), "contain", (0, 0, 500, 400)),
    ((-2550, 205, -1950, 905), (-2560, 200, 0, 1568), "snap", (-2560, 200, -1960, 900)),
    ((-700, 800, -10, 1558), (-2560, 200, 0, 1568), "snap", (-690, 810, 0, 1568)),
])
def test_window_placement_preserves_interior_and_only_changes_requested_axes(rect, work, placement, expected):
    from src.utils.windows import place_window_rect_in_work_area
    assert place_window_rect_in_work_area(rect, work, placement=placement) == expected


@pytest.mark.parametrize("dpi, frame, expected", [
    (96, (100, 200, 500, 600), None),
    (96, (1200, 500, 1910, 1070), (1202, 502)),
    (96, (1200, 500, 1900, 1060), None),
    (144, (1200, 500, 1900, 1060), (1212, 512)),
    (192, (1200, 500, 1890, 1050), (1222, 522)),
])
def test_native_snap_uses_visible_frame_and_scales_old_threshold_by_window_dpi(monkeypatch, dpi, frame, expected):
    import src.utils.windows as windows
    calls, areas = [], []
    monkeypatch.setattr(windows, "is_windows", lambda: True)
    def work_area(origin, ignored_hwnd):
        areas.append((origin, ignored_hwnd))
        return (0, 0, 1920, 1080), (0, 0, 1920, 1080)
    monkeypatch.setattr(windows, "get_visible_taskbar_work_area", work_area)
    user32 = SimpleNamespace(SetWindowPos=lambda *args: calls.append(args) or True, GetDpiForWindow=lambda _hwnd: dpi)
    monkeypatch.setattr(windows.ctypes, "WinDLL", lambda *_args, **_kwargs: user32, raising=False)
    monkeypatch.setattr(windows, "_configure_window_geometry_api", lambda _api: None)
    visible = SimpleNamespace(left=frame[0], top=frame[1], right=frame[2], bottom=frame[3])
    outer = SimpleNamespace(left=frame[0] - 8, top=frame[1] - 8)
    monkeypatch.setattr(windows, "_get_window_frame_rects", lambda *_args: (outer, visible))
    assert windows.position_windows_window_in_work_area(123, (0, 0), placement="snap")
    assert areas == [((0, 0), 123)]
    assert ([call[2:4] for call in calls] == [expected]) if expected else not calls


def test_sidebar_all_display_transitions_select_current_primary(monkeypatch):
    from src.gui.sidebar import sidebar_controller as module
    primary = SimpleNamespace(name=lambda: "Apollo")
    stale = SimpleNamespace(name=lambda: "ASUS")
    monkeypatch.setattr(module.QApplication, "instance", lambda: None)
    monkeypatch.setattr(module.QApplication, "primaryScreen", lambda: primary)
    controller = module.SidebarController(SimpleNamespace(), SimpleNamespace(screen=lambda: stale))
    selected = []
    controller._trigger = SimpleNamespace(reposition=lambda screen: selected.append(screen))
    controller._sidebar = SimpleNamespace(update_screen=lambda screen: selected.append(screen))
    assert controller._get_screen() is primary
    controller._on_primary_screen_changed(primary)
    controller._on_screen_config_changed(stale)
    assert selected == [primary] * 4


@pytest.mark.parametrize("work, frame, expected", [
    ((0, 0, 2560, 1368), (1900, 700, 2510, 1330), (1942, 730)),
    ((0, 0, 2560, 1440), (1900, 700, 2510, 1330), (1942, 802)),
    ((-2560, 200, 0, 1568), (-700, 800, -90, 1430), (-618, 930)),
])
def test_native_bottom_right_uses_visible_frame_and_shared_work_area(monkeypatch, work, frame, expected):
    import src.utils.windows as windows
    calls = []
    monkeypatch.setattr(windows, "is_windows", lambda: True)
    monkeypatch.setattr(windows, "get_visible_taskbar_work_area",
                        lambda origin, ignored_hwnd: ((origin[0], origin[1], work[2], work[3]), work))
    user32 = SimpleNamespace(SetWindowPos=lambda *args: calls.append(args) or True)
    monkeypatch.setattr(windows.ctypes, "WinDLL", lambda *_args, **_kwargs: user32, raising=False)
    monkeypatch.setattr(windows, "_configure_window_geometry_api", lambda _api: None)
    visible = SimpleNamespace(left=frame[0], top=frame[1], right=frame[2], bottom=frame[3])
    outer = SimpleNamespace(left=frame[0]-8, top=frame[1]-8)
    monkeypatch.setattr(windows, "_get_window_frame_rects", lambda *_args: (outer, visible))
    assert windows.position_windows_window_in_work_area(123, work[:2], placement="bottom_right")
    assert calls[0][2:4] == expected
    # The target frame already touches the work area's corner: no repeated move.
    visible.right, visible.bottom = work[2], work[3]
    calls.clear()
    assert windows.position_windows_window_in_work_area(123, work[:2], placement="bottom_right")
    assert calls == []


def test_sidebar_activates_when_running_cache_already_exists_without_monitor_change(monkeypatch, tmp_path):
    app = _qapp()
    main_window = _patch_main_window_deps(monkeypatch, tmp_path)
    process = ManagedProcess(id="game", name="Running Game", monitoring_path="game.exe", launch_path="game.exe")
    data_manager = _FakeApiClient([process])
    data_manager.global_settings.sidebar_enabled = True
    data_manager.global_settings.sidebar_mode = SIDEBAR_MODE_GAME
    data_manager.global_settings.hide_on_game = False
    window = main_window.MainWindow(data_manager)
    activated = []

    class _SidebarProbe:
        def activate_for_game(self, process_arg, pid=None, game_start_timestamp=None):
            activated.append((process_arg.id, pid, game_start_timestamp))

        def dispatch_recording_state(self, _state):
            pass

        def deactivate(self):
            raise AssertionError("steady-state running cache should not deactivate")

    try:
        window._sidebar_controller = _SidebarProbe()
        window._is_game_mode_active = False
        window.process_monitor.active_monitored_processes[process.id] = {
            "pid": 4321,
            "exe": process.monitoring_path,
            "start_time_approx": 100.0,
            "session_id": 1,
        }
        window.process_monitor.check_and_update_statuses = lambda: ProcessMonitorTickResult(changed=False)

        window.run_process_monitor_check()

        assert activated == [("game", 4321, None)]
        assert window._is_game_mode_active is True
    finally:
        _stop_window(window, app)


def test_game_mode_hide_keeps_qt_application_alive(monkeypatch, tmp_path):
    app = _qapp()
    main_window = _patch_main_window_deps(monkeypatch, tmp_path)
    process = ManagedProcess(id="game", name="Running Game", monitoring_path="game.exe", launch_path="game.exe")
    data_manager = _FakeApiClient([process])
    data_manager.global_settings.hide_on_game = True
    window = main_window.MainWindow(data_manager)
    hide_reasons = []

    class _TrayProbe:
        def hide_window_to_tray(self, reason):
            hide_reasons.append(reason)
            window.hide()

        def is_tray_icon_visible(self):
            return True

        def handle_window_close_event(self, event):
            event.ignore()
            self.hide_window_to_tray("window_close")

    try:
        # Simulate a regressed/alternate startup path where the QApplication
        # default would quit when the host window is hidden after game launch.
        app.setQuitOnLastWindowClosed(True)
        window.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, True)
        window.tray_manager = _TrayProbe()
        window._sidebar_controller = _Noop()
        window._is_game_mode_active = False
        window.process_monitor.active_monitored_processes[process.id] = {
            "pid": 4321,
            "exe": process.monitoring_path,
            "start_time_approx": 100.0,
            "session_id": 1,
        }
        window.process_monitor.check_and_update_statuses = lambda: ProcessMonitorTickResult(changed=False)

        window.run_process_monitor_check()

        assert hide_reasons == ["game_started"]
        assert app.quitOnLastWindowClosed() is False
        assert window.testAttribute(Qt.WidgetAttribute.WA_QuitOnClose) is False
        assert window._is_game_mode_active is True
    finally:
        _stop_window(window, app)


def test_default_volume_retry_does_not_crash_when_audio_session_is_late(monkeypatch):
    _qapp()
    import src.gui.main_window as main_window

    process = ManagedProcess(
        id="game",
        name="Running Game",
        monitoring_path="game.exe",
        launch_path="game.exe",
        default_volume=50,
        default_muted=False,
    )
    probe = SimpleNamespace(
        _volume_applied_pids={},
        _volume_retry_tokens={},
        _mute_retry_tokens={},
        data_manager=SimpleNamespace(managed_processes=[process]),
    )
    probe._get_active_pid = lambda process_id: 4321
    probe._sync_default_volume_state = MethodType(main_window.MainWindow._sync_default_volume_state, probe)
    scheduled = []

    def fail_volume(_pid, _level):
        return False

    def fail_mute(_pid, _muted):
        raise RuntimeError("late audio session")

    monkeypatch.setattr(main_window.audio_control, "set_app_volume", fail_volume)
    monkeypatch.setattr(main_window.audio_control, "set_mute", fail_mute)
    monkeypatch.setattr(
        main_window.QTimer,
        "singleShot",
        lambda delay, callback: scheduled.append((delay, callback)),
    )

    probe._sync_default_volume_state(process, 4321)

    assert [delay for delay, _callback in scheduled] == [500, 1000]
    assert probe._volume_retry_tokens == {"game": 1}
    assert probe._mute_retry_tokens == {"game": 1}


def test_sidebar_controller_can_enable_trigger_after_game_started_with_sidebar_disabled(monkeypatch):
    _qapp()
    import src.gui.sidebar.sidebar_controller as controller_module

    process = ManagedProcess(id="game", name="Running Game", monitoring_path="game.exe", launch_path="game.exe")
    settings = GlobalSettings(
        sidebar_mode=SIDEBAR_MODE_DISABLED,
        hide_on_game=False,
        sidebar_handle_auto_hide=False,
    )
    data_manager = type("DataManagerProbe", (), {"global_settings": settings})()
    trigger_events = []
    process_updates = []

    class _TriggerProbe:
        def __init__(self, *args, **kwargs):
            self.update_calls = []
            trigger_events.append((
                "created",
                kwargs.get("trigger_width_px"),
                kwargs.get("handle_auto_hide"),
            ))

        def start(self):
            trigger_events.append(("start", None))

        def stop(self):
            trigger_events.append(("stop", None))

        def update_settings(self, trigger_y_start, trigger_y_end, cooldown_sec, trigger_width_px=2, handle_auto_hide=True):
            self.update_calls.append((trigger_y_start, trigger_y_end, cooldown_sec, trigger_width_px, handle_auto_hide))
            trigger_events.append(("update", trigger_width_px))

    class _SidebarProbe:
        _is_shown = False

        def __init__(self, *args, **kwargs):
            process_updates.append(("created", kwargs.get("auto_hide_ms")))

        def update_process(self, process_arg, pid=None, game_start_timestamp=None):
            process_updates.append((process_arg.id, pid, game_start_timestamp))

        def update_auto_hide_ms(self, value):
            process_updates.append(("auto_hide", value))

        def apply_visual_settings(self):
            process_updates.append(("visual", None))

        def refresh_content(self):
            process_updates.append(("refresh", None))

        def slide_out(self):
            process_updates.append(("slide_out", None))

        def set_on_start_recording(self, _callback):
            pass

    monkeypatch.setattr(controller_module, "EdgeTriggerWindow", _TriggerProbe)
    monkeypatch.setattr(controller_module, "SidebarWidget", _SidebarProbe)

    controller = controller_module.SidebarController(data_manager)

    controller.activate_for_game(process, pid=4321, game_start_timestamp=100.0)

    assert controller._active_process is process
    assert trigger_events == []

    settings.sidebar_mode = SIDEBAR_MODE_GAME
    settings.sidebar_enabled = True
    controller.apply_settings(settings)

    assert ("created", settings.sidebar_edge_width_px, False) in trigger_events
    assert ("start", None) in trigger_events
    assert ("game", 4321, 100.0) in process_updates


def test_sidebar_controller_always_mode_starts_trigger_without_game(monkeypatch):
    _qapp()
    import src.gui.sidebar.sidebar_controller as controller_module

    settings = GlobalSettings(sidebar_mode=SIDEBAR_MODE_ALWAYS, hide_on_game=False)
    data_manager = type("DataManagerProbe", (), {"global_settings": settings})()
    trigger_events = []
    sidebar_events = []

    class _TriggerProbe:
        def __init__(self, *args, **kwargs):
            trigger_events.append((
                "created",
                kwargs.get("trigger_width_px"),
                kwargs.get("handle_auto_hide"),
            ))

        def start(self):
            trigger_events.append(("start", None))

        def stop(self):
            trigger_events.append(("stop", None))

        def update_settings(self, *args, **kwargs):
            trigger_events.append(("update", kwargs.get("trigger_width_px")))

    class _SidebarProbe:
        _is_shown = False

        def __init__(self, *args, **kwargs):
            sidebar_events.append(("created", kwargs.get("auto_hide_ms")))

        def update_process(self, *args, **kwargs):
            sidebar_events.append(("update_process", None))

        def update_auto_hide_ms(self, value):
            sidebar_events.append(("auto_hide", value))

        def apply_visual_settings(self):
            sidebar_events.append(("visual", None))

        def refresh_content(self):
            sidebar_events.append(("refresh", None))

        def slide_out(self):
            sidebar_events.append(("slide_out", None))

        def set_on_start_recording(self, _callback):
            pass

    monkeypatch.setattr(controller_module, "EdgeTriggerWindow", _TriggerProbe)
    monkeypatch.setattr(controller_module, "SidebarWidget", _SidebarProbe)

    controller = controller_module.SidebarController(data_manager)

    controller.apply_settings(settings)
    controller.deactivate()

    assert ("created", settings.sidebar_edge_width_px, True) in trigger_events
    assert trigger_events.count(("start", None)) == 2
    assert ("stop", None) not in trigger_events
    assert ("refresh", None) in sidebar_events


def test_sidebar_settings_dialog_persists_three_state_sidebar_mode(monkeypatch):
    import sys
    import types

    app = _qapp()
    monkeypatch.setitem(
        sys.modules,
        "src.screenshot.key_capture",
        types.SimpleNamespace(vk_to_display_name=lambda vk: f"VK 0x{vk:02X}"),
    )
    from src.gui.sidebar_settings_dialog import SidebarSettingsDialog

    settings = GlobalSettings(sidebar_mode=SIDEBAR_MODE_ALWAYS, hide_on_game=False)
    dialog = SidebarSettingsDialog(settings)
    try:
        assert dialog._mode_combo.currentData() == SIDEBAR_MODE_ALWAYS
        assert dialog._handle_auto_hide_cb.isChecked() is True

        disabled_index = dialog._mode_combo.findData(SIDEBAR_MODE_DISABLED)
        dialog._mode_combo.setCurrentIndex(disabled_index)
        dialog._handle_auto_hide_cb.setChecked(False)
        dialog._trigger_y_start_spin.setValue(0.85)
        dialog._trigger_y_end_spin.setValue(0.15)
        updated = dialog.get_updated_settings()

        assert updated.sidebar_mode == SIDEBAR_MODE_DISABLED
        assert updated.sidebar_enabled is False
        assert updated.sidebar_handle_auto_hide is False
        assert updated.sidebar_trigger_y_start == 0.15
        assert updated.sidebar_trigger_y_end == 0.85
    finally:
        dialog.deleteLater()
        app.processEvents()


def test_sidebar_controller_stops_trigger_immediately_when_sidebar_disabled(monkeypatch):
    _qapp()
    import src.gui.sidebar.sidebar_controller as controller_module

    process = ManagedProcess(id="game", name="Running Game", monitoring_path="game.exe", launch_path="game.exe")
    settings = GlobalSettings(sidebar_mode=SIDEBAR_MODE_GAME, hide_on_game=False)
    data_manager = type("DataManagerProbe", (), {"global_settings": settings})()
    trigger_events = []
    sidebar_events = []

    class _TriggerProbe:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            trigger_events.append("start")

        def stop(self):
            trigger_events.append("stop")

        def update_settings(self, *args, **kwargs):
            pass

    class _SidebarProbe:
        _is_shown = False

        def __init__(self, *args, **kwargs):
            self._is_shown = False

        def update_process(self, *args, **kwargs):
            pass

        def update_auto_hide_ms(self, *args, **kwargs):
            pass

        def apply_visual_settings(self):
            pass

        def refresh_content(self):
            pass

        def slide_out(self):
            sidebar_events.append("slide_out")

        def set_on_start_recording(self, _callback):
            pass

    monkeypatch.setattr(controller_module, "EdgeTriggerWindow", _TriggerProbe)
    monkeypatch.setattr(controller_module, "SidebarWidget", _SidebarProbe)

    controller = controller_module.SidebarController(data_manager)
    controller.activate_for_game(process, pid=4321, game_start_timestamp=100.0)
    controller._sidebar._is_shown = True

    settings.sidebar_mode = SIDEBAR_MODE_DISABLED
    settings.sidebar_enabled = False
    controller.apply_settings(settings)

    assert trigger_events == ["start", "stop"]
    assert sidebar_events == ["slide_out"]


def test_sidebar_controller_edge_trigger_callback_slides_sidebar_in(monkeypatch):
    _qapp()
    import src.gui.sidebar.sidebar_controller as controller_module

    process = ManagedProcess(id="game", name="Running Game", monitoring_path="game.exe", launch_path="game.exe")
    settings = GlobalSettings(sidebar_mode=SIDEBAR_MODE_GAME, hide_on_game=False)
    data_manager = type("DataManagerProbe", (), {"global_settings": settings})()
    triggers = []
    sidebar_events = []

    class _TriggerProbe:
        def __init__(self, *args, **kwargs):
            self.trigger_callback = kwargs["trigger_callback"]
            triggers.append(self)

        def start(self):
            pass

        def stop(self):
            pass

        def update_settings(self, *args, **kwargs):
            pass

    class _SidebarProbe:
        _is_shown = False

        def __init__(self, *args, **kwargs):
            pass

        def update_process(self, *args, **kwargs):
            pass

        def update_auto_hide_ms(self, *args, **kwargs):
            pass

        def apply_visual_settings(self):
            pass

        def refresh_content(self):
            pass

        def slide_out(self):
            sidebar_events.append("slide_out")

        def slide_in(self):
            sidebar_events.append("slide_in")

        def set_on_start_recording(self, _callback):
            pass

    monkeypatch.setattr(controller_module, "EdgeTriggerWindow", _TriggerProbe)
    monkeypatch.setattr(controller_module, "SidebarWidget", _SidebarProbe)

    controller = controller_module.SidebarController(data_manager)
    controller.activate_for_game(process, pid=4321, game_start_timestamp=100.0)

    assert len(triggers) == 1

    triggers[0].trigger_callback()

    assert sidebar_events == ["slide_in"]


def test_sidebar_controller_hides_handle_until_sidebar_finishes_hiding(monkeypatch):
    _qapp()
    import src.gui.sidebar.sidebar_controller as controller_module

    process = ManagedProcess(id="game", name="Running Game", monitoring_path="game.exe", launch_path="game.exe")
    settings = GlobalSettings(sidebar_mode=SIDEBAR_MODE_GAME, hide_on_game=False)
    data_manager = type("DataManagerProbe", (), {"global_settings": settings})()
    events = []
    triggers = []
    sidebars = []

    class _TriggerProbe:
        def __init__(self, *args, **kwargs):
            self.trigger_callback = kwargs["trigger_callback"]
            triggers.append(self)

        def start(self):
            events.append("trigger:start")

        def stop(self):
            events.append("trigger:stop")

        def update_settings(self, *args, **kwargs):
            pass

    class _SidebarProbe:
        _is_shown = False

        def __init__(self, *args, **kwargs):
            self._is_shown = False
            self._on_hidden = kwargs.get("on_hidden")
            sidebars.append(self)

        def update_process(self, *args, **kwargs):
            pass

        def update_auto_hide_ms(self, *args, **kwargs):
            pass

        def apply_visual_settings(self):
            pass

        def refresh_content(self):
            pass

        def slide_out(self):
            events.append("sidebar:slide_out")
            self._is_shown = False
            if self._on_hidden is not None:
                self._on_hidden()

        def slide_in(self):
            events.append("sidebar:slide_in")
            self._is_shown = True

        def set_on_start_recording(self, _callback):
            pass

    monkeypatch.setattr(controller_module, "EdgeTriggerWindow", _TriggerProbe)
    monkeypatch.setattr(controller_module, "SidebarWidget", _SidebarProbe)

    controller = controller_module.SidebarController(data_manager)
    controller.activate_for_game(process, pid=4321, game_start_timestamp=100.0)

    assert events == ["trigger:start"]
    assert len(triggers) == 1

    triggers[0].trigger_callback()

    assert events == ["trigger:start", "trigger:stop", "sidebar:slide_in"]
    assert sidebars[0]._is_shown is True

    sidebars[0].slide_out()

    assert events == [
        "trigger:start",
        "trigger:stop",
        "sidebar:slide_in",
        "sidebar:slide_out",
        "trigger:start",
    ]


def test_main_window_no_longer_schedules_foreground_focus():
    source = Path("src/gui/main_window.py").read_text(encoding="utf-8")

    assert "focus_process_window" not in source
    assert "_schedule_focus_after_launch" not in source


def test_main_window_reapplies_sidebar_startup_mode_after_native_show():
    source = Path("src/gui/main_window.py").read_text(encoding="utf-8")
    show_event_source = source[source.index("    def showEvent"):source.index("    def _on_monitor_timer_tick")]

    assert "_apply_sidebar_startup_mode" in show_event_source


def test_edge_trigger_visible_handle_uses_direct_paint_path():
    source = Path("src/gui/sidebar/edge_trigger_window.py").read_text(encoding="utf-8")

    assert "def paintEvent" in source
    assert "QPainter(self)" in source
    assert "_HANDLE_COLOR" in source
    assert "_HANDLE_GRIP_COLOR" in source


def test_edge_trigger_auto_hide_reveals_from_configured_edge_zone(monkeypatch):
    app = _qapp()
    cursor = {"pos": QPoint(0, 0)}

    class _CursorProbe:
        @staticmethod
        def pos():
            return cursor["pos"]

    monkeypatch.setattr(edge_trigger_module, "QCursor", _CursorProbe)

    edge = EdgeTriggerWindow(
        trigger_callback=lambda: None,
        trigger_y_start=0.25,
        trigger_y_end=0.5,
        trigger_width_px=12,
    )
    try:
        trigger_geometry = edge._trigger_geometry(edge._screen)
        assert trigger_geometry.height() < edge._screen.geometry().height()
        assert trigger_geometry.width() == 12

        edge.start()
        app.processEvents()

        assert edge._handle_visible is False
        assert edge._poll_timer.isActive()
        assert edge.geometry() == trigger_geometry
        assert edge.windowFlags() & Qt.WindowType.WindowTransparentForInput

        cursor["pos"] = trigger_geometry.center()
        edge._poll_cursor()
        app.processEvents()

        assert edge._handle_visible is True
        assert edge.geometry() == edge._handle_geometry(edge._screen)
        assert not edge.windowFlags() & Qt.WindowType.WindowTransparentForInput

        cursor["pos"] = edge._screen.geometry().center() - QPoint(100, 0)
        edge._poll_cursor()
        assert edge._handle_hide_timer.isActive()

        edge._handle_hide_timer.timeout.emit()
        app.processEvents()

        assert edge._handle_visible is False
        assert edge.geometry() == trigger_geometry
    finally:
        edge.stop()
        edge.deleteLater()
        app.processEvents()


def test_edge_trigger_starts_with_always_visible_borderless_click_handle():
    app = _qapp()
    edge = EdgeTriggerWindow(trigger_callback=lambda: None, trigger_width_px=2, handle_auto_hide=False)
    try:
        assert edge.windowFlags() & Qt.WindowType.WindowTransparentForInput

        edge.start()
        app.processEvents()

        assert edge._handle_visible is True
        assert edge._poll_timer.isActive()
        assert edge.geometry() == edge._handle_geometry(edge._screen)
        assert edge.geometry().width() > 2
        assert not edge.windowFlags() & Qt.WindowType.WindowTransparentForInput
        assert edge.windowOpacity() == 1.0
        assert "background: transparent" in edge.styleSheet()
        assert "border: none" in edge.styleSheet()

        rendered = QImage(edge.width(), edge.height(), QImage.Format.Format_ARGB32)
        rendered.fill(Qt.GlobalColor.transparent)
        edge.render(rendered)
        assert any(
            rendered.pixelColor(x, y).alpha() > 0
            for x in range(rendered.width())
            for y in range(rendered.height())
        )
    finally:
        edge.stop()
        edge.deleteLater()
        app.processEvents()


def test_edge_trigger_click_invokes_callback_without_hiding_handle():
    app = _qapp()
    triggered = []
    edge = EdgeTriggerWindow(
        trigger_callback=lambda: triggered.append(True),
        trigger_width_px=2,
        handle_auto_hide=False,
    )
    try:
        edge.start()
        app.processEvents()

        class _Click:
            def button(self):
                return Qt.MouseButton.LeftButton

            def accept(self):
                pass

        edge.mousePressEvent(_Click())
        edge.mousePressEvent(_Click())
        assert triggered == [True]
        assert edge._handle_visible is True
        assert not edge.windowFlags() & Qt.WindowType.WindowTransparentForInput
    finally:
        edge.stop()
        edge.deleteLater()
        app.processEvents()


def test_edge_trigger_applies_handle_geometry_after_input_flag_change(monkeypatch):
    app = _qapp()
    edge = EdgeTriggerWindow(trigger_callback=lambda: None, trigger_width_px=2)
    original_set_transparent = edge._set_transparent_for_input
    flag_calls = []
    try:
        expected_handle_geometry = edge._handle_geometry(edge._screen)

        def _resetting_flag_change(enabled):
            flag_calls.append(enabled)
            original_set_transparent(enabled)
            if enabled is False:
                # QWidget.setWindowFlag() may hide/recreate a top-level widget;
                # simulate a platform resetting geometry during that transition.
                edge.setGeometry(0, 0, 1, 1)

        monkeypatch.setattr(edge, "_set_transparent_for_input", _resetting_flag_change)

        edge._show_handle()
        app.processEvents()

        assert flag_calls == [False]
        assert edge.geometry() == expected_handle_geometry
        assert edge._handle_visible is True
        assert not edge.windowFlags() & Qt.WindowType.WindowTransparentForInput
    finally:
        edge.stop()
        edge.deleteLater()
        app.processEvents()


def test_edge_trigger_poll_restores_always_visible_handle_without_cursor_gate():
    app = _qapp()
    edge = EdgeTriggerWindow(trigger_callback=lambda: None, trigger_width_px=2, handle_auto_hide=False)
    try:
        edge.start()
        app.processEvents()
        edge._hide_handle()
        assert edge._handle_visible is False

        edge._poll_cursor()

        assert edge._handle_visible is True
        assert edge.geometry() == edge._handle_geometry(edge._screen)
    finally:
        edge.stop()
        edge.deleteLater()
        app.processEvents()


def test_edge_trigger_poll_restores_window_if_native_hide_keeps_handle_state():
    app = _qapp()
    edge = EdgeTriggerWindow(trigger_callback=lambda: None, trigger_width_px=2, handle_auto_hide=False)
    try:
        edge.start()
        app.processEvents()
        edge.hide()
        assert edge._handle_visible is True

        edge._poll_cursor()
        app.processEvents()

        assert edge.isVisible()
        assert edge.geometry() == edge._handle_geometry(edge._screen)
    finally:
        edge.stop()
        edge.deleteLater()
        app.processEvents()


def test_edge_trigger_start_uses_screen_handle_even_if_hidden_geometry_stale():
    app = _qapp()
    edge = EdgeTriggerWindow(trigger_callback=lambda: None, trigger_width_px=2, handle_auto_hide=False)
    try:
        edge._hide_handle()
        edge.setGeometry(0, 0, 1, 1)

        edge.start()
        app.processEvents()

        assert edge._handle_visible is True
        assert edge.geometry() == edge._handle_geometry(edge._screen)
    finally:
        edge.stop()
        edge.deleteLater()
        app.processEvents()


def test_sidebar_frame_css_remains_borderless():
    source = Path("src/gui/sidebar/sidebar_widget.py").read_text(encoding="utf-8")

    assert "border-left:" not in source
    assert "border: none;" in source


def test_process_icon_prefers_process_id_cache_without_existing_exe(monkeypatch, tmp_path):
    app = _qapp()
    cached_png = tmp_path / "cached-icon.png"
    pixmap = QPixmap(32, 32)
    pixmap.fill(QColor("#2a82da"))
    assert pixmap.save(str(cached_png))

    import src.api.dashboard.icons as icon_cache
    from src.utils.process import get_qicon_for_file

    monkeypatch.setattr(
        icon_cache,
        "get_icon_for_size",
        lambda process_id, requested_size: cached_png if process_id == "game-id" else None,
    )
    monkeypatch.setattr(
        icon_cache,
        "extract_icon_from_exe",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("cache hit should not extract")),
    )

    icon = get_qicon_for_file(str(tmp_path / "missing.exe"), icon_size=32, process_id="game-id")

    assert not icon.isNull()
    app.processEvents()


def test_restore_suspends_runtime_timers_and_monitor_cache():
    import threading
    import types
    import src.gui.main_window as main_window

    class FakeTimer:
        def __init__(self):
            self.active = True
            self.start_calls = []
            self.stop_calls = 0

        def isActive(self):
            return self.active

        def stop(self):
            self.active = False
            self.stop_calls += 1

        def start(self, interval):
            self.active = True
            self.start_calls.append(interval)

    monitor_timer = FakeTimer()
    scheduler_timer = FakeTimer()
    heartbeat_timer = FakeTimer()
    ui_timer = FakeTimer()
    process_monitor = types.SimpleNamespace(active_monitored_processes={"game-a": {"session_id": 1}})
    resource_shutdown_calls = []
    timer_registry = main_window.DesiredTimerRegistry()
    timer_registry.register("startup_reconcile", FakeTimer(), interval_ms=1000)
    timer_registry.register("monitor", monitor_timer, interval_ms=1000)
    timer_registry.register("scheduler", scheduler_timer, interval_ms=1000)
    timer_registry.register("heartbeat", heartbeat_timer, interval_ms=30000)
    timer_registry.register("ui_refresh", ui_timer, interval_ms=1000)
    window = types.SimpleNamespace(
        _beholder_restore_runtime_suspended=False,
        _lifecycle_shutdown_event=threading.Event(),
        process_monitor=process_monitor,
        monitor_timer=monitor_timer,
        scheduler_timer=scheduler_timer,
        runtime_heartbeat_timer=heartbeat_timer,
        ui_refresh_timer=ui_timer,
        _UI_REFRESH_INTERVAL_MS=1000,
        _timer_registry=timer_registry,
        _work_coordinator=types.SimpleNamespace(
            invalidate_telemetry=lambda: None,
            shutdown=lambda **_kwargs: resource_shutdown_calls.append("work") or True,
        ),
        _hoyolab_reconcile=types.SimpleNamespace(shutdown=lambda *_args: resource_shutdown_calls.append("hoyo") or True),
        _nikke_resource_reconcile=types.SimpleNamespace(shutdown=lambda *_args: resource_shutdown_calls.append("nikke") or True),
        _daily_checkin=types.SimpleNamespace(shutdown=lambda *_args: resource_shutdown_calls.append("checkin") or True),
    )

    assert main_window.MainWindow.prepare_database_restore(window) is True
    main_window.MainWindow._ensure_timers_running(window)

    assert window._beholder_restore_runtime_suspended is True
    assert process_monitor.active_monitored_processes == {}
    assert monitor_timer.stop_calls == 1
    assert scheduler_timer.stop_calls == 1
    assert heartbeat_timer.stop_calls == 1
    assert monitor_timer.start_calls == []
    assert scheduler_timer.start_calls == []
    assert resource_shutdown_calls == ["hoyo", "nikke", "checkin", "work"]
    assert window._lifecycle_shutdown_event.is_set()


def test_windows_title_bar_color_noops_off_windows(monkeypatch):
    import src.utils.windows as windows

    monkeypatch.setattr(windows.os, "name", "posix")

    assert windows.apply_windows_title_bar_color(
        1234,
        caption_color=(53, 53, 53),
        text_color=(220, 220, 220),
        dark_mode=True,
    ) is False


def test_admin_feature_setting_is_saved_without_restart_or_rollback(monkeypatch, tmp_path):
    app = _qapp()
    main_window = _patch_main_window_deps(monkeypatch, tmp_path)
    data = _FakeApiClient([])
    window = main_window.MainWindow(data)
    updated = GlobalSettings(run_as_admin=True, run_on_startup=True, sidebar_enabled=False)
    dialog = SimpleNamespace(exec=lambda: True, get_updated_settings=lambda: updated)
    monkeypatch.setattr(main_window, "GlobalSettingsDialog", lambda *_args: dialog)
    try:
        window.open_global_settings_dialog()
        assert data.global_settings.run_as_admin is True
        assert data.global_settings.run_on_startup is True
        assert window.launcher.run_as_admin is True
        assert window.isVisible()
    finally:
        _stop_window(window, app)


@pytest.fixture
def sidebar_layout(monkeypatch):
    from src.gui.main_window import MainWindow
    from src.gui.sidebar import sidebar_widget as module
    monkeypatch.setattr(MainWindow, "INSTANCE", None)
    app = _qapp()
    names = ["명조: 위더링 웨이브", "붕괴: 스타레일(베타)", "소녀전선2: 망명", "긴 이름의 게임 등록 항목 이름", "W" * 80]
    data = _FakeApiClient([
        ManagedProcess(id=str(index), name=name, monitoring_path=f"/test/{index}.exe", launch_path=f"/test/{index}.exe")
        for index, name in enumerate(names)
    ])
    view = module.SidebarWidget(data)
    monkeypatch.setattr(view, "_load_icon_async", lambda *_args: None)
    data.global_settings.obs_watch_output_dir = False
    view.refresh_content()
    try:
        yield app, view, module
    finally:
        assert view.cleanup(deadline_ms=200)
        view.close()


def test_sidebar_cards_and_sound_follow_main_name_order_and_keep_action_targets(sidebar_layout, monkeypatch):
    from PySide6.QtWidgets import QSlider
    from src.gui.main_window import MainWindow
    _app, view, module = sidebar_layout
    # Input/launch order intentionally differs from name order, including equal names.
    games = [
        ManagedProcess(id="z", name="젠레스 존 제로", monitoring_path="/z.exe", launch_path="/z.exe"),
        ManagedProcess(id="b", name="Alpha", monitoring_path="/b.exe", launch_path="/b.exe"),
        ManagedProcess(id="m", name="명조", monitoring_path="/m.exe", launch_path="/m.exe"),
        ManagedProcess(id="a", name="alpha", monitoring_path="/a.exe", launch_path="/a.exe"),
        ManagedProcess(id="idle", name="니케", monitoring_path="/idle.exe", launch_path="/idle.exe"),
    ]
    view._data_manager.managed_processes = games
    active = {game.id: {"pid": 100 + index, "start_time_approx": 1000.0 - index}
              for index, game in enumerate(games) if game.id != "idle"}
    active["deleted"] = {"pid": 999, "start_time_approx": 1.0}
    monkeypatch.setattr(MainWindow, "INSTANCE", SimpleNamespace(process_monitor=SimpleNamespace(active_monitored_processes=active)))
    monkeypatch.setattr(module.audio_control, "get_app_volume", lambda _pid: None)
    monkeypatch.setattr(module.audio_control, "is_muted", lambda _pid: False)
    volume_calls = []
    monkeypatch.setattr(view, "_on_vol_list_changed", lambda value, game, pid: volume_calls.append((game.id, pid, value)))
    stopped = []
    monkeypatch.setattr(view, "_kill_process", lambda *args: stopped.append(args))
    original = [game.to_dict() for game in games]
    active_before = {key: dict(value) for key, value in active.items()}
    view._refresh_active_sections()
    view._refresh_volumes_list()
    active_order = ["a", "b", "m", "z"]
    assert list(view._playtime_labels) == active_order
    for index, game_id in enumerate(active_order):
        cluster = view._active_clusters_layout.itemAt(index).widget()
        game = next(game for game in games if game.id == game_id)
        assert next(label.text() for label in cluster.findChildren(QLabel) if label.text() == game.name) == game.name
        cluster.findChild(QPushButton).click()
        assert stopped[-1] == (game_id, game.monitoring_path, active[game_id]["pid"], active[game_id]["start_time_approx"])
        assert view._playtime_labels[game_id][1] == active[game_id]["start_time_approx"]
    sound_order = ["a", "b", "idle", "m", "z"]
    for index, game_id in enumerate(sound_order):
        row = view._vol_list_layout.itemAt(index).widget()
        game = next(game for game in games if game.id == game_id)
        assert next(label.text() for label in row.findChildren(QLabel) if label.wordWrap()) == game.name
        row.findChild(QSlider).setValue(35)
        assert volume_calls[-1] == (game_id, active.get(game_id, {}).get("pid"), 35)
    assert [game.to_dict() for game in games] == original
    assert active == active_before


def test_sidebar_name_edit_and_running_set_refresh_reapply_sort_without_reordering_source(sidebar_layout, monkeypatch):
    from src.gui.main_window import MainWindow
    _app, view, module = sidebar_layout
    games = view._data_manager.managed_processes
    active = {game.id: {"pid": 100 + index, "start_time_approx": 1000.0 + index} for index, game in enumerate(games)}
    monkeypatch.setattr(MainWindow, "INSTANCE", SimpleNamespace(process_monitor=SimpleNamespace(active_monitored_processes=active)))
    monkeypatch.setattr(module.audio_control, "get_app_volume", lambda _pid: None)
    monkeypatch.setattr(module.audio_control, "is_muted", lambda _pid: False)
    ids = [game.id for game in games]
    view.refresh_content()
    assert list(view._playtime_labels) == ["4", "3", "0", "1", "2"]
    games[2].name = "Alpha"
    active.pop("4")
    view.refresh_content()
    assert list(view._playtime_labels) == ["2", "3", "0", "1"]
    assert [next(label.text() for label in view._vol_list_layout.itemAt(index).widget().findChildren(QLabel) if label.wordWrap())
            for index in range(len(games))] == ["Alpha", "W" * 80, "긴 이름의 게임 등록 항목 이름", "명조: 위더링 웨이브", "붕괴: 스타레일(베타)"]
    assert [game.id for game in games] == ids
    active.clear()
    view._refresh_active_sections()
    assert not view._playtime_labels and not view._active_clusters_layout.count()
    view._data_manager.managed_processes = []
    view._refresh_volumes_list()
    assert view._vol_list_layout.itemAt(0).widget().text() == "등록된 게임 없음"


@pytest.mark.parametrize("height", [250, 1400])
def test_sidebar_long_names_do_not_clip_other_rows_or_controls(sidebar_layout, height):
    from PySide6.QtWidgets import QSlider
    app, view, _module = sidebar_layout
    view.resize(280, height)
    view.show()
    for _ in range(3):
        app.processEvents()
    assert view.width() == 280
    viewport = view._main_scroll.viewport()
    assert view._scroll_content.width() <= viewport.width()
    rows = view._vol_list_container.findChildren(QSlider)
    assert len(rows) == 5
    for slider in rows:
        row = slider.parentWidget()
        name = next(label for label in row.findChildren(QLabel) if label.wordWrap())
        assert name.width() > 0
        assert name.height() >= name.heightForWidth(name.width())
        for widget in row.findChildren(QPushButton) + row.findChildren(QLabel) + [slider]:
            if widget.isVisible():
                right = widget.mapTo(view._scroll_content, QPoint(widget.width(), 0)).x()
                assert right <= viewport.width(), (name.text(), right, viewport.width())
    # Native label metrics can post a final nested layout request while measured.
    QCoreApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
    app.processEvents()
    assert not view._main_scroll.verticalScrollBar().isVisible()
    assert (view._main_scroll.verticalScrollBar().maximum() > 0) is (height == 250)
    assert viewport.width() == view._main_scroll.contentsRect().width()


def test_sidebar_height_change_preserves_hidden_scroll_and_wheel_access(sidebar_layout):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QWheelEvent
    app, view, _module = sidebar_layout
    view.resize(280, 1400)
    view.show()
    for _ in range(3):
        app.processEvents()
    scroll = view._main_scroll
    assert scroll.verticalScrollBar().maximum() == 0
    view.resize(280, 250)
    for _ in range(3):
        app.processEvents()
    assert scroll.verticalScrollBar().maximum() > 0
    assert not scroll.verticalScrollBar().isVisible()
    viewport = scroll.viewport()
    assert viewport.width() == scroll.contentsRect().width()
    position = viewport.rect().center()
    event = QWheelEvent(QPointF(position), QPointF(viewport.mapToGlobal(position)), QPoint(), QPoint(0, -120),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    app.sendEvent(viewport, event)
    app.processEvents()
    assert scroll.verticalScrollBar().value() > 0
    view.resize(280, 1400)
    for _ in range(3):
        app.processEvents()
    assert scroll.verticalScrollBar().maximum() == 0
    assert scroll.verticalScrollBar().value() == 0
    assert not scroll.verticalScrollBar().isVisible()


def test_sidebar_active_game_and_gallery_buttons_share_visible_width(sidebar_layout):
    app, view, _module = sidebar_layout
    view._data_manager.global_settings.screenshot_enabled = True
    view._data_manager.global_settings.recording_enabled = True
    view._data_manager.global_settings.sidebar_playtime_prefix = "W" * 80
    process = view._data_manager.managed_processes[-1]
    cluster = view._make_game_cluster(process, 42, 123.0)
    view._active_clusters_layout.addWidget(cluster)
    view._refresh_screenshot_section()
    view._refresh_recording_section()
    view.resize(280, 500)
    view.show()
    app.processEvents()
    viewport = view._main_scroll.viewport()
    assert view._scroll_content.width() <= viewport.width()
    for button in view._scroll_content.findChildren(QPushButton):
        if button.isVisible():
            assert button.mapTo(view._scroll_content, QPoint(button.width(), 0)).x() <= viewport.width()


@pytest.fixture
def sidebar_gallery(sidebar_layout, tmp_path, monkeypatch):
    app, view, module = sidebar_layout
    screenshots = tmp_path / "screenshots"
    recordings = tmp_path / "recordings"
    screenshots.mkdir()
    recordings.mkdir()
    for index in range(12):
        path = screenshots / f"image-{index:02}.png"
        image = QImage(40, 30, QImage.Format.Format_RGB32)
        image.fill(QColor("blue"))
        assert image.save(str(path))
        video = recordings / f"video-{index:02}.mp4"
        video.write_bytes(b"synthetic video fixture; never decoded")
        os.utime(path, (1000 + index, 1000 + index))
        os.utime(video, (1000 + index, 1000 + index))
    gs = view._data_manager.global_settings
    gs.screenshot_enabled = True
    gs.screenshot_save_dir = str(screenshots)
    gs.recording_enabled = True
    gs.obs_watch_output_dir = True
    view._recording_output_dir = str(recordings)
    # Synthetic files only; prevent Windows Shell decoding or external operations.
    tasks = []
    monkeypatch.setattr(view._thumb_pool, "start", tasks.append)
    monkeypatch.setattr(view._rec_thumb_pool, "start", tasks.append)
    view.refresh_content()
    view.resize(280, 1100)
    view.show()
    for _ in range(3):
        app.processEvents()
    yield app, view, module, screenshots, recordings, tasks


def _gallery_widgets(view):
    return [view._gallery_layout.itemAt(index).widget() for index in range(view._gallery_layout.count())]


@pytest.mark.parametrize("height", [700, 1100])
def test_sidebar_clock_and_bottom_group_stay_at_edges_with_three_row_cap(sidebar_gallery, height):
    app, view, _module, _screenshots, _recordings, _tasks = sidebar_gallery
    view.resize(280, height)
    for _ in range(4):
        app.processEvents()
    margins = view._frame.layout().contentsMargins()
    assert view._clock_widget.geometry().top() == margins.top()
    assert view._close_btn.geometry().bottom() == view.height() - margins.bottom() - 1
    assert view._clock_widget.parentWidget() is view._frame
    assert view._close_btn.parentWidget() is view._frame
    assert view._media_section.geometry().bottom() == view._scroll_content.height() - 1
    assert view._gallery.geometry().bottom() == view._media_section.height() - 1
    _width, cell_height, gap = view._gallery_cell_size()
    assert view._gallery.height() == 3 * cell_height + 2 * gap
    assert len(_gallery_widgets(view)) == 9
    assert view._scroll_layout.itemAt(1).spacerItem().geometry().height() > 0
    assert view._main_scroll.verticalScrollBar().maximum() == 0


def test_sidebar_extreme_height_scrolls_middle_only_and_recovers_bottom_alignment(sidebar_gallery):
    app, view, _module, _screenshots, _recordings, _tasks = sidebar_gallery
    view.resize(280, 250)
    for _ in range(4):
        app.processEvents()
    clock = view._clock_widget.geometry()
    close = view._close_btn.geometry()
    bar = view._main_scroll.verticalScrollBar()
    assert bar.maximum() > 0 and not bar.isVisible()
    assert clock.top() >= 0 and close.bottom() < view.height()
    bar.setValue(bar.maximum())
    app.processEvents()
    assert view._clock_widget.geometry() == clock
    assert view._close_btn.geometry() == close
    assert len(_gallery_widgets(view)) == 3
    view.resize(280, 1100)
    for _ in range(4):
        app.processEvents()
    assert bar.maximum() == 0 and bar.value() == 0
    assert view._media_section.geometry().bottom() == view._scroll_content.height() - 1
    assert len(_gallery_widgets(view)) == 9


def test_sidebar_running_indicator_follows_game_identity_after_name_and_session_changes(sidebar_layout, monkeypatch):
    from src.gui.main_window import MainWindow
    app, view, module = sidebar_layout
    active = {"0": {"pid": 123}}
    monkeypatch.setattr(MainWindow, "INSTANCE", SimpleNamespace(process_monitor=SimpleNamespace(active_monitored_processes=active)))
    monkeypatch.setattr(module.audio_control, "get_app_volume", lambda _pid: None)
    monkeypatch.setattr(module.audio_control, "is_muted", lambda _pid: False)
    for running_id in ("0", "2"):
        active.clear()
        active[running_id] = {"pid": 123}
        view._data_manager.managed_processes[2].name = "Alpha"
        view._refresh_volumes_list()
        view.resize(280, 700)
        view.show()
        for _ in range(3):
            app.processEvents()
        for index, game in enumerate(sorted(view._data_manager.managed_processes, key=ManagedProcess.name_sort_key)):
            row = view._vol_list_layout.itemAt(index).widget()
            dot = row.layout().itemAt(0).widget()
            name = row.layout().itemAt(1).widget()
            assert name.text() == game.name
            assert dot.geometry().right() < name.geometry().left()
            color = dot.palette().color(dot.foregroundRole())
            if game.id == running_id:
                assert color.alpha() > 0 and color.green() > color.red()
            else:
                assert color.alpha() == 0


def test_sidebar_balanced_layout_with_full_game_names_fits_controls_and_bottom_gallery(sidebar_gallery, monkeypatch):
    import time
    from src.gui.main_window import MainWindow
    from PySide6.QtWidgets import QSlider
    app, view, module, _screenshots, _recordings, _tasks = sidebar_gallery
    names = ["명조: 위더링 웨이브", "몬길: STAR DIVE", "붕괴: 스타레일", "붕괴: 스타레일(베타)",
             "소녀전선2: 망명", "승리의 여신: 니케", "젠레스 존 제로"]
    games = [ManagedProcess(id=str(index), name=name, monitoring_path=f"/test/{index}.exe", launch_path=f"/test/{index}.exe")
             for index, name in enumerate(names)]
    view._data_manager.managed_processes = games
    active = {"0": {"pid": 123, "start_time_approx": time.time() - 80 * 60}}
    monkeypatch.setattr(MainWindow, "INSTANCE", SimpleNamespace(process_monitor=SimpleNamespace(active_monitored_processes=active)))
    monkeypatch.setattr(module.audio_control, "get_app_volume", lambda _pid: None)
    monkeypatch.setattr(module.audio_control, "is_muted", lambda _pid: False)
    view.on_recording_state_changed("idle")
    view.refresh_content()
    view.resize(280, 800)
    for _ in range(4):
        app.processEvents()
    for index in range(len(games)):
        row = view._vol_list_layout.itemAt(index).widget()
        name = next(label for label in row.findChildren(QLabel) if label.wordWrap())
        slider = row.findChild(QSlider)
        value = row.layout().itemAt(4).widget()
        assert name.height() >= name.heightForWidth(name.width())
        assert value.width() >= value.fontMetrics().horizontalAdvance(value.text())
        assert slider.geometry().right() < value.geometry().left()
        assert value.geometry().right() < row.width()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
    app.processEvents()
    assert len(_gallery_widgets(view)) == 9
    assert view._main_scroll.verticalScrollBar().maximum() == 0
    assert view._media_section.geometry().bottom() == view._scroll_content.height() - 1


def test_sidebar_content_replace_hides_old_rows_before_deferred_delete(sidebar_gallery, monkeypatch):
    import time
    from src.gui.main_window import MainWindow
    app, view, module, _screenshots, _recordings, _tasks = sidebar_gallery
    active = {"0": {"pid": 123, "start_time_approx": time.time()}}
    monkeypatch.setattr(MainWindow, "INSTANCE", SimpleNamespace(process_monitor=SimpleNamespace(active_monitored_processes=active)))
    monkeypatch.setattr(module.audio_control, "get_app_volume", lambda _pid: None)
    monkeypatch.setattr(module.audio_control, "is_muted", lambda _pid: False)
    view.refresh_content()
    app.processEvents()
    old_card = view._active_clusters_layout.itemAt(0).widget()
    old_rows = [view._vol_list_layout.itemAt(index).widget() for index in range(view._vol_list_layout.count())]
    assert old_card.isVisible() and all(row.isVisible() for row in old_rows)
    view.refresh_content()
    # No event loop/DeferredDelete between replacement and this assertion.
    assert old_card.isHidden() and all(row.isHidden() for row in old_rows)
    assert view._active_clusters_layout.itemAt(0).widget() is not old_card
    assert all(view._vol_list_layout.itemAt(index).widget() is not row for index, row in enumerate(old_rows))


def test_sidebar_clock_date_rollover_preserves_format_and_visibility(sidebar_layout, monkeypatch):
    import datetime
    _app, view, _module = sidebar_layout
    class Clock(datetime.datetime):
        @classmethod
        def now(cls):
            return cls.current
    monkeypatch.setattr(datetime, "datetime", Clock)
    gs = view._data_manager.global_settings
    gs.sidebar_clock_format = "%H:%M"
    for now, date_text in [(Clock(2026, 10, 14, 23, 59), "10월 14일 수요일"),
                           (Clock(2026, 10, 15, 0, 0), "10월 15일 목요일")]:
        Clock.current = now
        view._update_clock()
        assert view._clock_label.text() == now.strftime("%H:%M")
        assert view._clock_date_label.text() == date_text
    gs.sidebar_clock_enabled = False
    view._update_clock()
    assert view._clock_widget.isHidden()


@pytest.mark.parametrize("state, text, action", [
    ("idle", "연결됨", "_rec_start_btn"),
    ("recording", "01:01:01", "_rec_stop_btn"),
    ("connecting", "연결 중", None),
    ("obs_offline", "연결 안 됨", "_rec_connect_btn"),
])
def test_sidebar_recording_status_and_action_share_one_row(sidebar_gallery, state, text, action):
    app, view, _module, _screenshots, _recordings, _tasks = sidebar_gallery
    view.set_recording_elapsed_provider(lambda: 3661)
    view.on_recording_state_changed(state)
    for _ in range(3):
        app.processEvents()
    status = view._rec_status_label
    assert status.text() == text
    section = view._recording_section
    assert status.parentWidget() is section
    for name in ("_rec_start_btn", "_rec_stop_btn", "_rec_connect_btn"):
        button = getattr(view, name)
        assert button.isVisible() is (name == action)
        if button.isVisible():
            assert button.parentWidget() is section
            assert abs(button.geometry().center().y() - status.geometry().center().y()) <= 1
            assert button.geometry().right() < section.width()
    assert section.height() == view._screenshot_section.height()
    assert not section.styleSheet()  # Parent transparency must not erase button backgrounds.


def test_sidebar_shared_gallery_height_reduces_previews_before_scrolling(sidebar_gallery):
    app, view, _module, screenshots, _recordings, _tasks = sidebar_gallery
    # Exclude the new flexible gap above the bottom group, as well as the gallery.
    fixed_height = (view.height() - view._gallery.height()
                    - view._scroll_layout.itemAt(1).spacerItem().geometry().height())
    cell_width, cell_height, gap = view._gallery_cell_size()
    for rows in [3, 2, 1, 3]:
        view.resize(view.width(), fixed_height + rows * cell_height + (rows - 1) * gap)
        for _ in range(3):
            app.processEvents()
        widgets = _gallery_widgets(view)
        assert len(widgets) == rows * 3
        assert widgets[-1].text() == f"+{12 - (rows * 3 - 1)}"
        assert [path for path, cell in view._thumb_buttons.items() if not cell.isHidden()] == [str(screenshots / f"image-{index:02}.png")
                                           for index in range(11, 11 - (rows * 3 - 1), -1)]
        assert view._main_scroll.verticalScrollBar().maximum() == 0
        assert not view._main_scroll.verticalScrollBar().isVisible()
        assert view._main_scroll.viewport().width() == view._main_scroll.contentsRect().width()
        assert all(widget.width() == cell_width and widget.height() == cell_height for widget in widgets)
        assert max(widget.geometry().bottom() for widget in widgets) < view._gallery.height()
        assert view._capture_now_btn.isVisible() and view._rec_connect_btn.isVisible()
    # When mandatory controls cannot fit either, wheel access stays available.
    view.resize(280, 250)
    for _ in range(3):
        app.processEvents()
    assert view._main_scroll.verticalScrollBar().maximum() > 0
    assert not view._main_scroll.verticalScrollBar().isVisible()
    assert len(_gallery_widgets(view)) == 3
    assert next(button for button in view.findChildren(QPushButton) if button.text() == "닫기").isVisible()


def test_sidebar_shared_gallery_switch_keeps_actions_and_rejects_late_results(sidebar_gallery, monkeypatch):
    app, view, module, screenshots, recordings, _tasks = sidebar_gallery
    old_request = view._thumb_request_id
    image = module._ThumbnailLoadTask._build_thumbnail(str(screenshots / "image-11.png"))
    assert image is not None
    called = []
    view.set_on_start_recording(lambda: called.append("start"))
    view.set_on_stop_recording(lambda: called.append("stop"))
    view.set_on_reconnect_recording(lambda: called.append("reconnect"))
    view._gallery_tabs.setCurrentIndex(1)
    app.processEvents()
    assert not view._thumb_buttons and len(view._rec_thumb_buttons) == 8
    assert all(str(recordings) in path for path in view._rec_thumb_buttons)
    view._apply_thumbnail_result(old_request, str(screenshots / "image-11.png"), image)
    assert not view._thumb_cache
    old_video_request = view._rec_thumb_request_id
    view._rec_connect_btn.click()
    view.on_recording_state_changed("idle")
    view._rec_start_btn.click()
    view.on_recording_state_changed("recording")
    view._rec_stop_btn.click()
    assert called == ["reconnect", "start", "stop"]
    view._gallery_tabs.setCurrentIndex(0)
    app.processEvents()
    view._apply_rec_thumbnail_result(old_video_request, str(recordings / "video-11.mp4"), image)
    assert not view._rec_thumb_cache and not view._rec_thumb_buttons
    view._apply_thumbnail_result(view._thumb_request_id, str(screenshots / "image-11.png"), image)
    assert view._thumb_buttons[str(screenshots / "image-11.png")].pixmap() is not None
    assert str(screenshots / "image-11.png") in view._thumb_cache
    opened = []
    monkeypatch.setattr(module.os, "startfile", opened.append, raising=False)
    _gallery_widgets(view)[-1].click()
    assert opened == [str(screenshots)]


def test_sidebar_shared_gallery_refresh_follows_selected_source_and_path(sidebar_gallery):
    app, view, _module, screenshots, recordings, tasks = sidebar_gallery
    new_image = screenshots / "new.png"
    new_image.write_bytes((screenshots / "image-11.png").read_bytes())
    request = view._thumb_request_id
    view.on_screenshot_captured(str(new_image))
    for _ in range(3):
        app.processEvents()
    assert view._thumb_request_id > request
    assert next(iter(view._thumb_buttons)) == str(new_image)
    assert _gallery_widgets(view)[-1].text() == "+5"
    view._gallery_tabs.setCurrentIndex(1)
    app.processEvents()
    request = view._rec_thumb_request_id
    # An event for the hidden source does not rebuild the visible source.
    task_count = len(tasks)
    view._refresh_screenshot_thumbnails()
    assert view._rec_thumb_request_id == request and len(tasks) == task_count
    empty = recordings.parent / "empty"
    empty.mkdir()
    view.set_recording_output_dir(str(empty))
    assert not view._rec_thumb_buttons
    assert len(_gallery_widgets(view)) == 1 and not _gallery_widgets(view)[0].text()
    view._apply_rec_thumbnail_result(request, str(recordings / "video-11.mp4"), QImage(4, 3, QImage.Format.Format_RGB32))
    assert not view._rec_thumb_cache
    view.set_recording_output_dir(str(empty / "missing"))
    assert not _gallery_widgets(view)
    view.set_recording_output_dir(str(recordings))
    view.refresh_content()
    app.processEvents()
    assert view._gallery_tabs.tabData(view._gallery_tabs.currentIndex()) == "recording"
    assert len(view._rec_thumb_buttons) == 8


def test_sidebar_shared_gallery_resize_reuses_cells_and_same_source_results(sidebar_gallery):
    app, view, module, screenshots, _recordings, tasks = sidebar_gallery
    path = str(screenshots / "image-11.png")
    image = module._ThumbnailLoadTask._build_thumbnail(path)
    view._apply_thumbnail_result(view._thumb_request_id, path, image)
    old_request = view._thumb_request_id
    fixed_height = (view.height() - view._gallery.height()
                    - view._scroll_layout.itemAt(1).spacerItem().geometry().height())
    width, height, _gap = view._gallery_cell_size()
    tasks.clear()
    view.resize(280, fixed_height + height)
    for _ in range(3):
        app.processEvents()
    assert sum(not cell.isHidden() for cell in view._thumb_buttons.values()) == 2
    assert view._thumb_request_id == old_request
    assert view._thumb_buttons[path].pixmap().size() == QSize(width, height)
    assert not any(task._path == path for task in tasks)
    omitted_path = str(screenshots / "image-04.png")
    view._apply_thumbnail_result(old_request, omitted_path, image)
    assert view._thumb_buttons[omitted_path].isHidden()
    # A same-name file updated on disk must be decoded again.
    os.utime(path, (9000, 9000))
    tasks.clear()
    view._refresh_screenshot_thumbnails()
    assert any(task._path == path for task in tasks)


def test_sidebar_resize_never_reads_files_or_restarts_thumbnail_work(sidebar_gallery, monkeypatch):
    app, view, _module, _screenshots, _recordings, tasks = sidebar_gallery
    cells = dict(view._thumb_buttons)
    request = view._thumb_request_id
    tasks.clear()
    def forbidden(*_args, **_kwargs):
        pytest.fail("resize must not inspect files or recreate gallery content")
    monkeypatch.setattr(Path, "iterdir", forbidden)
    monkeypatch.setattr(Path, "stat", forbidden)
    for height in (1050, 950, 850, 750, 650, 950, 1100):
        view.resize(280, height)
        app.processEvents()
    assert view._thumb_buttons == cells
    assert view._thumb_request_id == request and not tasks
    assert _gallery_widgets(view)[-1].text() == "+4"


def test_sidebar_opening_ignores_outside_cursor_until_animation_finishes(sidebar_gallery, monkeypatch):
    from PySide6.QtGui import QCursor
    _app, view, _module, _screenshots, _recordings, _tasks = sidebar_gallery
    monkeypatch.setattr(view, "_compute_geometry", lambda: QRect(0, 0, 280, 1100))
    monkeypatch.setattr(QCursor, "pos", lambda: QPoint(290, 500))
    view._auto_hide_ms = 0
    view.slide_in()
    view._poll_cursor()
    assert view._is_shown and view.isVisible()
    view._anim.setCurrentTime(view._anim.duration())
    view._poll_cursor()
    assert not view._is_shown


def test_sidebar_close_interrupted_by_reopen_cannot_hide_new_open(sidebar_gallery, monkeypatch):
    _app, view, _module, _screenshots, _recordings, _tasks = sidebar_gallery
    monkeypatch.setattr(view, "_compute_geometry", lambda: QRect(0, 0, 280, 1100))
    hidden = []
    view._on_hidden = lambda: hidden.append(True)
    view.slide_in()
    view._anim.setCurrentTime(view._anim.duration())
    view.slide_out()
    view._anim.setCurrentTime(50)
    view.slide_in()
    view._anim.setCurrentTime(view._anim.duration())
    assert view._is_shown and view.isVisible() and not hidden
    view.slide_out()
    view._anim.setCurrentTime(view._anim.duration())
    assert not view._is_shown and not view.isVisible() and hidden == [True]


@pytest.mark.parametrize("saved, expected", [(0, 0), (35, 35), (None, 100)])
def test_sidebar_saved_volume_zero_is_preserved(sidebar_layout, saved, expected):
    from PySide6.QtWidgets import QSlider
    _app, view, _module = sidebar_layout
    view._data_manager.managed_processes = [ManagedProcess(
        id="zero", name="Muted Game", monitoring_path="/test/zero.exe", launch_path="/test/zero.exe", default_volume=saved,
    )]
    view._refresh_volumes_list()
    row = view._vol_list_layout.itemAt(0).widget()
    assert row.findChild(QSlider).value() == expected


@pytest.mark.parametrize("kind", ["screenshot", "recording"])
def test_sidebar_shared_gallery_delete_updates_folder_count_without_changing_source(sidebar_gallery, monkeypatch, kind):
    import sys
    from PySide6.QtWidgets import QMessageBox
    app, view, _module, _screenshots, _recordings, _tasks = sidebar_gallery
    view._gallery_tabs.setCurrentIndex(0 if kind == "screenshot" else 1)
    app.processEvents()
    buttons = view._thumb_buttons if kind == "screenshot" else view._rec_thumb_buttons
    cache = view._thumb_cache if kind == "screenshot" else view._rec_thumb_cache
    refresh = view._refresh_screenshot_thumbnails if kind == "screenshot" else view._refresh_recording_thumbnails
    path = next(iter(buttons))
    assert _gallery_widgets(view)[-1].text() == "+4"
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Yes)
    monkeypatch.setitem(sys.modules, "winshell", SimpleNamespace(delete_file=lambda path, **_kwargs: Path(path).unlink()))
    view._delete_gallery_file(path, cache=cache, refresh=refresh)
    app.processEvents()
    assert path not in buttons and not Path(path).exists()
    assert _gallery_widgets(view)[-1].text() == "+3"
    assert view._gallery_tabs.tabData(view._gallery_tabs.currentIndex()) == kind


def test_sidebar_shared_gallery_removed_choice_falls_back_only_when_needed(sidebar_gallery):
    app, view, _module, _screenshots, _recordings, _tasks = sidebar_gallery
    gs = view._data_manager.global_settings
    view._gallery_tabs.setCurrentIndex(1)
    gs.screenshot_enabled = False
    view.refresh_content()
    app.processEvents()
    assert view._gallery_tabs.tabData(view._gallery_tabs.currentIndex()) == "recording"
    gs.screenshot_enabled = True
    gs.obs_watch_output_dir = False
    view.refresh_content()
    app.processEvents()
    assert view._gallery_tabs.tabData(view._gallery_tabs.currentIndex()) == "screenshot"
    assert not view._rec_thumb_buttons
    gs.obs_watch_output_dir = True
    view.refresh_content()
    app.processEvents()
    assert view._gallery_tabs.tabData(view._gallery_tabs.currentIndex()) == "screenshot"


@pytest.mark.parametrize("screenshots, control, files", [
    (False, False, False), (False, False, True), (False, True, False), (False, True, True),
    (True, False, False), (True, False, True), (True, True, False), (True, True, True),
])
def test_sidebar_shared_gallery_settings_keep_file_and_control_boundaries(sidebar_gallery, screenshots, control, files):
    app, view, _module, _screenshots, _recordings, _tasks = sidebar_gallery
    gs = view._data_manager.global_settings
    gs.screenshot_enabled = screenshots
    gs.recording_enabled = control
    gs.obs_watch_output_dir = files
    view.refresh_content()
    app.processEvents()
    sources = [view._gallery_tabs.tabData(index) for index in range(view._gallery_tabs.count())]
    assert sources == (["screenshot"] if screenshots else []) + (["recording"] if files else [])
    assert view._gallery.isHidden() is not (screenshots or files)
    assert view._capture_now_btn.isVisible() is screenshots
    assert view._rec_status_label.isVisible() is control
    assert view._rec_connect_btn.isVisible() is control
    assert view._recording_section.isHidden() is not (control or files)
    if not screenshots:
        assert not view._thumb_buttons
    if not files:
        assert not view._rec_thumb_buttons


@pytest.mark.parametrize("work, expected", [
    ((0, 0, 3840, 2080), QRect(1640, 0, 280, 1040)),
    ((0, 0, 3840, 2160), QRect(1640, 0, 280, 1080)),
    ((0, 80, 3840, 2160), QRect(1640, 40, 280, 1040)),
    ((80, 0, 3840, 2160), QRect(1640, 0, 280, 1080)),
    ((0, 0, 3760, 2160), QRect(1600, 0, 280, 1080)),
])
def test_sidebar_maps_native_taskbar_area_to_monitor_logical_coordinates(sidebar_layout, monkeypatch, work, expected):
    _app, view, module = sidebar_layout
    view._screen = SimpleNamespace(name=lambda: "DISPLAY", geometry=lambda: QRect(0, 0, 1920, 1080),
                                   availableGeometry=lambda: QRect(0, 0, 1920, 1040))
    monkeypatch.setattr(module, "get_visible_taskbar_work_area", lambda *_args: ((0, 0, 3840, 2160), work))
    assert view._compute_geometry() == expected


def test_sidebar_secondary_monitor_negative_origin_and_height_ratio(sidebar_layout, monkeypatch):
    _app, view, module = sidebar_layout
    view._screen = SimpleNamespace(name=lambda: "SECONDARY", geometry=lambda: QRect(-2560, 200, 1280, 720),
                                   availableGeometry=lambda: QRect(-2560, 200, 1280, 680))
    view._data_manager.global_settings.sidebar_height_ratio = 0.5
    monkeypatch.setattr(module, "get_visible_taskbar_work_area", lambda *_args: ((-2560, 200, 0, 1640), (-2560, 200, 0, 1560)))
    assert view._compute_geometry() == QRect(-1560, 370, 280, 340)
    monkeypatch.setattr(module, "get_visible_taskbar_work_area", lambda *_args: None)
    assert view._compute_geometry() == QRect(-1560, 370, 280, 340)


def test_sidebar_existing_cursor_poll_updates_height_but_not_running_slide(sidebar_layout, monkeypatch):
    _app, view, _module = sidebar_layout
    from PySide6.QtGui import QCursor
    area = QRect(0, 0, 280, 600)
    view._is_shown = True
    monkeypatch.setattr(view, "_compute_geometry", lambda: area)
    monkeypatch.setattr(QCursor, "pos", lambda: QPoint(20, 20))
    view._poll_cursor()
    assert view.geometry() == area
    area = QRect(0, 0, 280, 650)
    view._poll_cursor()
    assert view.geometry() == area
    view._anim.setStartValue(area)
    view._anim.setEndValue(QRect(-280, 0, 280, 650))
    view._anim.start()
    before = view.geometry()
    area = QRect(0, 0, 280, 700)
    view._poll_cursor()
    assert view.geometry() == before
    assert view._cursor_poll_timer.interval() == 200
    view._anim.stop()


@pytest.mark.parametrize("taskbar, surface, reserved, expected", [
    ((0, 1040, 1920, 1080), 1, (0, 0, 1920, 1040), (0, 0, 1920, 1040)),
    ((0, 1040, 1920, 1080), 3, (0, 0, 1920, 1040), (0, 0, 1920, 1080)),  # covered
    ((0, 1078, 1920, 1120), 1, (0, 0, 1920, 1080), (0, 0, 1920, 1080)),  # hidden edge
    ((0, 0, 1920, 40), 1, (0, 40, 1920, 1080), (0, 40, 1920, 1080)),
    ((0, 0, 40, 1080), 1, (40, 0, 1920, 1080), (40, 0, 1920, 1080)),
    ((1880, 0, 1920, 1080), 1, (0, 0, 1880, 1080), (0, 0, 1880, 1080)),
    ((1880, 0, 1920, 1080), 2, (0, 0, 1880, 1080), (0, 0, 1880, 1080)),  # own overlay
    ((0, 1020, 1920, 1080), 1, (0, 0, 1920, 1040), (0, 0, 1920, 1040)),  # transparent margin
    ((0, 1040, 1920, 1080), 1, (0, 0, 1920, 1080), (0, 0, 1920, 1040)),  # revealed auto-hide
])
def test_native_taskbar_visibility_not_reserved_area(monkeypatch, taskbar, surface, reserved, expected):
    import sys
    import src.utils.windows as windows
    monitor = (0, 0, 1920, 1080)
    monkeypatch.setattr(windows, "is_windows", lambda: True)
    monkeypatch.setitem(sys.modules, "win32api", SimpleNamespace(
        EnumDisplayMonitors=lambda: [(10, None, monitor)],
        GetMonitorInfo=lambda _handle: {"Device": "DISPLAY", "Monitor": monitor, "Work": reserved},
    ))
    monkeypatch.setitem(sys.modules, "win32con", SimpleNamespace(GW_HWNDNEXT=2, GWL_EXSTYLE=-20, WS_EX_TRANSPARENT=32))
    monkeypatch.setitem(sys.modules, "win32gui", SimpleNamespace(
        # Reproduce the live omission: generic enumeration sees no taskbar.
        EnumWindows=lambda *_args: pytest.fail("Taskbar lookup must not enumerate app windows"),
        FindWindowEx=lambda _parent, previous, cls, _name: 1 if cls == "Shell_SecondaryTrayWnd" and not previous else 0,
        IsWindowVisible=lambda _hwnd: True, IsIconic=lambda _hwnd: False,
        GetWindowRect=lambda hwnd: taskbar if hwnd == 1 else monitor,
        WindowFromPoint=lambda _point: surface,
        GetAncestor=lambda hwnd, _flag: hwnd,
        GetWindow=lambda hwnd, _flag: 1 if hwnd == 2 else 0,
        GetWindowLong=lambda _hwnd, _index: 0,
    ))
    assert windows.get_visible_taskbar_work_area((0, 0), ignored_hwnd=2) == (monitor, expected)
    assert windows.get_visible_taskbar_work_area((1920, 0), ignored_hwnd=2) is None


def test_native_taskbar_api_failure_returns_unavailable(monkeypatch):
    import sys
    import src.utils.windows as windows
    monkeypatch.setattr(windows, "is_windows", lambda: True)
    monkeypatch.setitem(sys.modules, "win32api", SimpleNamespace(EnumDisplayMonitors=lambda: (_ for _ in ()).throw(OSError("unavailable"))))
    monkeypatch.setitem(sys.modules, "win32gui", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "win32con", SimpleNamespace())
    assert windows.get_visible_taskbar_work_area((0, 0)) is None
