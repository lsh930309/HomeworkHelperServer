import os
import datetime
import logging
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)

from PyQt6.QtWidgets import (
    QTableWidgetItem, QDialog, QVBoxLayout, QLabel, QTableWidget,
    QDialogButtonBox, QHeaderView, QWidget, QFormLayout, QPushButton,
    QLineEdit, QHBoxLayout, QFileDialog, QMessageBox, QCheckBox,
    QTimeEdit, QDoubleSpinBox, QSpinBox, QComboBox, QGroupBox, QApplication,
    QRadioButton, QButtonGroup, QTextEdit, QGridLayout,
)
from PyQt6.QtCore import Qt, QTime, QThread, pyqtSignal
from PyQt6.QtGui import QIcon # QIcon might be needed if dialogs use icons directly

# Local imports
from src.data.data_models import ManagedProcess, GlobalSettings
from src.utils.process import get_all_running_processes_info # Used by RunningProcessSelectionDialog
from src.utils.common import copy_shortcut_file # 바로가기 파일 복사 기능
from src.utils.resource_tracking import NIKKE_OUTPOST_LABEL
import requests
from src.api.runtime_config import resolve_api_port, resolve_local_api_base_url


class _RemoteSettingsWorker(QThread):
    """Run a remote-settings HTTP/probe task without blocking dialog creation."""

    succeeded = pyqtSignal(str, object)
    failed = pyqtSignal(str, object)

    def __init__(self, task_name: str, task, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.task_name = task_name
        self._task = task

    def run(self):
        try:
            self.succeeded.emit(self.task_name, self._task())
        except Exception as exc:
            self.failed.emit(self.task_name, exc)


class RemoteSettingsDialog(QDialog):
    """Compact remote setup dialog for server-mode, pairing, device and readiness tasks."""

    def __init__(self, data_manager, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.data_manager = data_manager
        self.base_url = resolve_local_api_base_url(getattr(data_manager, "base_url", None))
        self._workers: list[_RemoteSettingsWorker] = []
        self.setWindowTitle("원격 설정")
        self.setMinimumWidth(680)
        self.resize(680, 520)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        self._build_pairing_section(root)
        self._build_server_section(root)
        self._build_remote_access_section(root)
        self._build_status_section(root)
        self._build_devices_section(root)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.button_box.rejected.connect(self.reject)
        root.addWidget(self.button_box)

        self._schedule_initial_refreshes()

    def _build_pairing_section(self, root: QVBoxLayout) -> None:
        group = QGroupBox("페어링")
        layout = QVBoxLayout(group)
        layout.setSpacing(6)

        headline = QLabel("macOS/Android 리모트 클라이언트에서 입력할 6자리 코드")
        headline.setWordWrap(True)
        layout.addWidget(headline)

        code_row = QHBoxLayout()
        self.pairing_code_edit = QLineEdit()
        self.pairing_code_edit.setReadOnly(True)
        self.pairing_code_edit.setPlaceholderText("코드 발급")
        self.pairing_code_edit.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        code_font = self.pairing_code_edit.font()
        code_font.setPointSize(max(code_font.pointSize() + 10, 20))
        code_font.setBold(True)
        self.pairing_code_edit.setFont(code_font)
        self.pairing_code_edit.setMinimumHeight(44)
        issue_button = QPushButton("발급")
        issue_button.clicked.connect(self._issue_pairing_code)
        copy_button = QPushButton("복사")
        copy_button.clicked.connect(lambda: QApplication.clipboard().setText(self.pairing_code_edit.text()))
        code_row.addWidget(self.pairing_code_edit, 1)
        code_row.addWidget(issue_button)
        code_row.addWidget(copy_button)
        layout.addLayout(code_row)

        self.pairing_status_label = QLabel("최초 페어링 성공 후에는 명시적 언페어링 전까지 token으로 자동 연결됩니다.")
        self.pairing_status_label.setWordWrap(True)
        layout.addWidget(self.pairing_status_label)
        root.addWidget(group)

    def _build_server_section(self, root: QVBoxLayout) -> None:
        group = QGroupBox("호스트 서버")
        layout = QGridLayout(group)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(6)

        self.remote_server_mode_checkbox = QCheckBox(f"리모트 서버 모드로 시작 (0.0.0.0:{resolve_api_port()})")
        self.remote_server_mode_checkbox.setChecked(bool(getattr(self.data_manager.global_settings, "remote_server_mode_enabled", False)))
        self.remote_server_mode_checkbox.setToolTip("다음 앱 실행부터 Tailscale/LAN 클라이언트 접속을 허용합니다.")
        save_button = QPushButton("서버 모드 저장")
        save_button.clicked.connect(self._save_server_mode)
        self.remote_desktop_log_checkbox = QCheckBox("원격 진단 로그를 바탕 화면에 저장")
        self.remote_desktop_log_checkbox.setToolTip("HomeworkHelperRemoteHost.log에 페어링/Tailscale/전원 설정 이벤트를 JSONL로 기록합니다.")
        log_button = QPushButton("로그 저장")
        log_button.clicked.connect(self._save_remote_logging_config)
        self.server_status_label = QLabel("서버 모드 변경은 앱 재시작 후 적용됩니다. 로그 설정을 불러오는 중...")
        self.server_status_label.setWordWrap(True)

        layout.addWidget(self.remote_server_mode_checkbox, 0, 0)
        layout.addWidget(save_button, 0, 1)
        layout.addWidget(self.remote_desktop_log_checkbox, 1, 0)
        layout.addWidget(log_button, 1, 1)
        layout.addWidget(self.server_status_label, 2, 0, 1, 2)
        layout.setColumnStretch(0, 1)
        root.addWidget(group)

    def _build_remote_access_section(self, root: QVBoxLayout) -> None:
        group = QGroupBox("공개 HTTPS 직접접속")
        layout = QGridLayout(group)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(6)

        self.remote_access_summary_label = QLabel("공개 HTTPS: 확인 대기")
        self.remote_access_summary_label.setWordWrap(True)
        self.remote_access_url_edit = QLineEdit()
        self.remote_access_url_edit.setReadOnly(True)
        self.remote_access_url_edit.setPlaceholderText("공인 IP 감지 후 https://<ip>.sslip.io 생성")
        self.remote_access_rule_label = QLabel("공유기 수동 포트포워딩: TCP 443 → Windows Host 38443")
        self.remote_access_rule_label.setWordWrap(True)
        self.remote_access_details_text = QTextEdit()
        self.remote_access_details_text.setReadOnly(True)
        self.remote_access_details_text.setMaximumHeight(110)
        self.remote_access_details_text.setPlainText("Caddy sidecar, UPnP 진단, 보안 경고를 불러오는 중... Remote Agent 8000은 공개하지 않습니다.")

        refresh_button = QPushButton("공개 HTTPS 새로고침")
        refresh_button.clicked.connect(self._refresh_remote_access)
        copy_button = QPushButton("URL 복사")
        copy_button.clicked.connect(lambda: QApplication.clipboard().setText(self.remote_access_url_edit.text()))

        layout.addWidget(self.remote_access_summary_label, 0, 0)
        layout.addWidget(refresh_button, 0, 1)
        layout.addWidget(copy_button, 0, 2)
        layout.addWidget(self.remote_access_url_edit, 1, 0, 1, 3)
        layout.addWidget(self.remote_access_rule_label, 2, 0, 1, 3)
        layout.addWidget(self.remote_access_details_text, 3, 0, 1, 3)
        layout.setColumnStretch(0, 1)
        root.addWidget(group)

    def _build_status_section(self, root: QVBoxLayout) -> None:
        group = QGroupBox("연결/전원 상태")
        layout = QGridLayout(group)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(6)

        self.tailscale_summary_label = QLabel("Tailscale: 확인 대기")
        self.tailscale_summary_label.setWordWrap(True)
        self.power_status_label = QLabel("전원 준비: 확인 대기")
        self.power_status_label.setWordWrap(True)
        self.tailscale_health_text = QTextEdit()
        self.tailscale_health_text.setReadOnly(True)
        self.tailscale_health_text.setMaximumHeight(78)
        self.tailscale_health_text.setPlainText("Tailscale 상태를 불러오는 중...")
        self.power_setup_text = QTextEdit()
        self.power_setup_text.setReadOnly(True)
        self.power_setup_text.setMaximumHeight(94)
        self.power_setup_text.setPlainText("호스트 전원 준비 상태를 불러오는 중...")

        tailscale_refresh = QPushButton("Tailscale 새로고침")
        tailscale_refresh.clicked.connect(self._refresh_tailscale)
        ensure_button = QPushButton("설치/실행 확인")
        ensure_button.clicked.connect(self._ensure_tailscale)
        tailscale_up_button = QPushButton("Tailscale 활성화")
        tailscale_up_button.clicked.connect(self._tailscale_up)
        tailscale_down_button = QPushButton("Tailscale 비활성화")
        tailscale_down_button.clicked.connect(self._tailscale_down)
        power_refresh = QPushButton("전원 상태 확인")
        power_refresh.clicked.connect(self._refresh_power_setup)

        layout.addWidget(self.tailscale_summary_label, 0, 0)
        layout.addWidget(tailscale_refresh, 0, 1)
        layout.addWidget(ensure_button, 0, 2)
        layout.addWidget(tailscale_up_button, 1, 1)
        layout.addWidget(tailscale_down_button, 1, 2)
        layout.addWidget(self.tailscale_health_text, 2, 0, 1, 3)
        layout.addWidget(self.power_status_label, 3, 0)
        layout.addWidget(power_refresh, 3, 1, 1, 2)
        layout.addWidget(self.power_setup_text, 4, 0, 1, 3)
        layout.setColumnStretch(0, 1)
        root.addWidget(group)

    def _build_devices_section(self, root: QVBoxLayout) -> None:
        group = QGroupBox("Tailnet 기기")
        layout = QVBoxLayout(group)
        layout.setSpacing(6)
        self.devices_table = QTableWidget(0, 8)
        self.devices_table.setHorizontalHeaderLabels(["ID", "역할", "이름", "Tailnet IP", "OS", "페어링", "통신 상태", "마지막 통신"])
        self.devices_table.setColumnHidden(0, True)
        self.devices_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.devices_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.devices_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.devices_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.devices_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        if self.devices_table.horizontalHeader():
            self.devices_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        buttons = QHBoxLayout()
        refresh_button = QPushButton("새로고침")
        refresh_button.clicked.connect(self._refresh_devices)
        self.revoke_button = QPushButton("선택 언페어링")
        self.revoke_button.clicked.connect(self._revoke_selected_device)
        purge_button = QPushButton("폐기 목록 정리")
        purge_button.clicked.connect(self._purge_revoked_devices)
        buttons.addWidget(refresh_button)
        buttons.addWidget(self.revoke_button)
        buttons.addWidget(purge_button)
        buttons.addStretch(1)
        layout.addWidget(self.devices_table)
        layout.addLayout(buttons)
        root.addWidget(group)

    def _device_sort_key_for_host(self, device: dict) -> tuple[int, str, str]:
        pairing_status = str(device.get("pairing_status") or ("revoked" if device.get("revoked_at") else "paired"))
        role = str(device.get("role") or "unknown")
        if role == "host":
            rank = 0
        elif pairing_status == "paired":
            rank = 1
        elif pairing_status == "tailnet_unpaired":
            rank = 2
        elif pairing_status == "revoked":
            rank = 3
        else:
            rank = 2
        name = str(
            device.get("name")
            or device.get("tailnet_hostname")
            or device.get("tailnet_dns_name")
            or device.get("tailnet_ip")
            or device.get("id")
            or ""
        ).casefold()
        return (rank, name, str(device.get("tailnet_ip") or device.get("id") or ""))

    def _fit_devices_table_to_rows(self) -> None:
        """Show every paired-device row without an internal vertical scrollbar."""
        header = self.devices_table.horizontalHeader()
        header_height = header.height() if header and not header.isHidden() else 0
        visible_rows = max(self.devices_table.rowCount(), 1)
        rows_height = sum(
            self.devices_table.rowHeight(row)
            for row in range(self.devices_table.rowCount())
        )
        if self.devices_table.rowCount() == 0:
            rows_height = self.devices_table.verticalHeader().defaultSectionSize()
        frame_height = self.devices_table.frameWidth() * 2
        horizontal_scroll_height = (
            self.devices_table.horizontalScrollBar().sizeHint().height()
            if self.devices_table.horizontalScrollBarPolicy() != Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            else 0
        )
        target_height = header_height + rows_height + frame_height + horizontal_scroll_height
        self.devices_table.setFixedHeight(max(target_height, header_height + frame_height + visible_rows))
        self.adjustSize()

    def _schedule_initial_refreshes(self) -> None:
        self._refresh_remote_logging_config()
        self._refresh_remote_access()
        self._refresh_devices()
        self._refresh_tailscale()
        self._refresh_power_setup()

    def _start_worker(self, task_name: str, task) -> None:
        worker = _RemoteSettingsWorker(task_name, task, self)
        worker.succeeded.connect(self._on_worker_succeeded)
        worker.failed.connect(self._on_worker_failed)
        worker.finished.connect(lambda w=worker: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(worker)
        worker.start()

    def _on_worker_succeeded(self, task_name: str, payload: object) -> None:
        if task_name == "logging":
            self._apply_remote_logging_config(payload if isinstance(payload, dict) else {})
        elif task_name == "devices":
            devices = payload if isinstance(payload, list) else []
            self._populate_devices(devices)
        elif task_name == "tailscale":
            self._apply_tailscale_payload(payload if isinstance(payload, dict) else {})
        elif task_name == "remote_access":
            self._apply_remote_access_payload(payload if isinstance(payload, dict) else {})
        elif task_name == "tailscale_ensure":
            self._apply_tailscale_ensure_payload(payload if isinstance(payload, dict) else {})
        elif task_name in {"tailscale_up", "tailscale_down"}:
            self._apply_tailscale_control_payload(payload if isinstance(payload, dict) else {})
        elif task_name == "power":
            self._apply_power_setup_payload(payload if isinstance(payload, dict) else {})

    def _on_worker_failed(self, task_name: str, exc: object) -> None:
        if task_name == "logging":
            self.server_status_label.setText(f"원격 로그 설정 조회 실패: {exc}")
        elif task_name == "devices":
            self.pairing_status_label.setText(f"기기 목록 조회 실패: {exc}")
        elif task_name in {"tailscale", "tailscale_ensure", "tailscale_up", "tailscale_down"}:
            self.tailscale_summary_label.setText("Tailscale: 조회 실패")
            self.tailscale_health_text.setPlainText(f"Tailscale 상태 조회 실패: {exc}")
        elif task_name == "remote_access":
            self.remote_access_summary_label.setText("공개 HTTPS: 조회 실패")
            self.remote_access_details_text.setPlainText(f"공개 HTTPS 상태 조회 실패: {exc}")
        elif task_name == "power":
            self.power_status_label.setText("전원 준비: 조회 실패")
            self.power_setup_text.setPlainText(f"전원 준비 상태 조회 실패: {exc}")

    def _refresh_remote_logging_config(self):
        self.server_status_label.setText("원격 로그 설정을 불러오는 중...")
        def task():
            response = requests.get(f"{self.base_url}/remote/logging/config", timeout=5)
            response.raise_for_status()
            return response.json()
        self._start_worker("logging", task)

    def _apply_remote_logging_config(self, payload: dict) -> None:
        self.remote_desktop_log_checkbox.setChecked(bool(payload.get("enabled")))
        self.server_status_label.setText(f"원격 로그: {payload.get('path') or '경로 미확인'}")

    def _refresh_remote_access(self):
        self.remote_access_summary_label.setText("공개 HTTPS: 확인 중...")
        self.remote_access_details_text.setPlainText("공개 IP, Caddy, UPnP 상태를 불러오는 중...")
        def task():
            response = requests.get(f"{self.base_url}/remote/access/status", timeout=8)
            response.raise_for_status()
            return response.json()
        self._start_worker("remote_access", task)

    def _apply_remote_access_payload(self, payload: dict) -> None:
        public_url = str(payload.get("public_base_url") or "")
        router_rule = payload.get("router_rule") if isinstance(payload.get("router_rule"), dict) else {}
        caddy = payload.get("caddy") if isinstance(payload.get("caddy"), dict) else {}
        upnp = payload.get("upnp") if isinstance(payload.get("upnp"), dict) else {}
        warnings = payload.get("warnings") if isinstance(payload.get("warnings"), list) else []
        advisories = payload.get("advisories") if isinstance(payload.get("advisories"), list) else []
        self.remote_access_url_edit.setText(public_url)
        self.remote_access_summary_label.setText(
            f"공개 HTTPS: {payload.get('state') or 'unknown'} · {payload.get('message') or '상태 미확인'}"
        )
        self.remote_access_rule_label.setText(
            f"공유기 수동 포트포워딩: {router_rule.get('summary') or 'TCP 443 -> Windows Host:38443'}"
        )
        self.remote_access_details_text.setPlainText(
            "공개 HTTPS 직접접속\n"
            f"- public_ip: {payload.get('public_ip') or '미감지'} ({payload.get('public_ip_source') or 'unknown'})\n"
            f"- hostname: {payload.get('hostname') or '미생성'}\n"
            f"- caddy: installed={caddy.get('installed')} running={caddy.get('running')} listener={caddy.get('listener')}\n"
            f"- caddy_config: {caddy.get('config_path') or ''}\n"
            f"- upnp: {upnp.get('state') or 'unknown'} · {upnp.get('message') or ''}\n"
            f"- warnings: {warnings}\n"
            f"- advisories: {advisories}\n"
            f"\nCaddyfile preview:\n{caddy.get('config_preview') or ''}"
        )

    def _save_remote_logging_config(self):
        try:
            response = requests.put(
                f"{self.base_url}/remote/logging/config",
                json={"enabled": self.remote_desktop_log_checkbox.isChecked()},
                timeout=5,
            )
            response.raise_for_status()
            payload = response.json()
            self._apply_remote_logging_config(payload)
        except requests.RequestException as exc:
            QMessageBox.warning(self, "로그 설정 실패", str(exc))

    def _save_server_mode(self):
        previous = bool(getattr(self.data_manager.global_settings, "remote_server_mode_enabled", False))
        updated = GlobalSettings.from_dict(self.data_manager.global_settings.to_dict())
        updated.remote_server_mode_enabled = self.remote_server_mode_checkbox.isChecked()
        if self.data_manager.save_global_settings(updated, actor="remote_settings_dialog"):
            self.server_status_label.setText("저장되었습니다. 앱 재시작 후 API 바인딩에 적용됩니다.")
            if previous != self.remote_server_mode_checkbox.isChecked():
                QMessageBox.information(
                    self,
                    "재시작 필요",
                    "리모트 서버 모드 설정이 변경되었습니다.\n\nAPI 서버 바인딩 주소를 적용하려면 앱을 재시작해주세요.",
                )
        else:
            QMessageBox.warning(self, "저장 실패", "리모트 서버 모드 설정 저장에 실패했습니다.")

    def _issue_pairing_code(self):
        try:
            response = requests.post(f"{self.base_url}/remote/pair/start", timeout=5)
            response.raise_for_status()
            payload = response.json()
            self.pairing_code_edit.setText(str(payload.get("code") or ""))
            self.pairing_code_edit.selectAll()
            self.pairing_status_label.setText(f"코드 발급 완료. 만료: {payload.get('expires_at')}")
        except requests.RequestException as exc:
            QMessageBox.warning(self, "페어링 코드 발급 실패", str(exc))

    def _refresh_devices(self):
        self.pairing_status_label.setText("페어링된 기기 목록을 불러오는 중...")
        def task():
            response = requests.get(f"{self.base_url}/remote/devices", timeout=5)
            response.raise_for_status()
            return response.json().get("devices", [])
        self._start_worker("devices", task)

    def _populate_devices(self, devices: list) -> None:
        pairing_labels = {
            "paired": "페어링됨",
            "revoked": "폐기됨",
            "host": "호스트",
            "tailnet_unpaired": "미페어링",
        }
        connectivity_labels = {
            "active": "정상",
            "local": "로컬",
            "revoked": "폐기됨",
            "tailnet_online": "Tailnet 온라인",
            "tailnet_online_unpaired": "Tailnet 온라인",
            "tailnet_offline": "Tailnet 오프라인",
            "tailnet_offline_unpaired": "Tailnet 오프라인",
            "stale_or_offline": "대기/오프라인",
            "unknown": "미확인",
        }
        self.devices_table.setRowCount(0)
        for device in sorted(devices, key=self._device_sort_key_for_host):
            row = self.devices_table.rowCount()
            self.devices_table.insertRow(row)
            pairing_status = device.get("pairing_status") or ("revoked" if device.get("revoked_at") else "paired")
            connectivity_state = device.get("connectivity_state") or ""
            is_host_self = device.get("role") == "host"
            values = [
                device.get("id") or "",
                device.get("role") or "unknown",
                device.get("name") or "",
                device.get("tailnet_ip") or "",
                device.get("tailnet_os") or device.get("platform") or "",
                "-" if is_host_self else pairing_labels.get(pairing_status, pairing_status),
                "-" if is_host_self else connectivity_labels.get(connectivity_state, connectivity_state),
                str(device.get("last_seen_at") or ""),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if is_host_self:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable & ~Qt.ItemFlag.ItemIsEnabled)
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, bool(device.get("can_revoke", not device.get("revoked_at"))))
                if col == 5:
                    item.setToolTip(str(pairing_status))
                elif col == 6:
                    item.setToolTip(str(device.get("health_message") or connectivity_state))
                self.devices_table.setItem(row, col, item)
        self._fit_devices_table_to_rows()
        self.pairing_status_label.setText(f"Tailnet/페어링 기기 {len(devices)}개")

    def _revoke_selected_device(self):
        row = self.devices_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "선택 필요", "언페어링할 기기를 선택하세요.")
            return
        item = self.devices_table.item(row, 0)
        device_id = item.text() if item else ""
        can_revoke = bool(item.data(Qt.ItemDataRole.UserRole)) if item else False
        if not can_revoke:
            QMessageBox.information(self, "언페어링 불가", "Host, 폐기된 기기 또는 아직 페어링되지 않은 tailnet 기기는 언페어링 대상이 아닙니다.")
            return
        if not device_id:
            return
        try:
            response = requests.delete(f"{self.base_url}/remote/devices/{device_id}", timeout=5)
            response.raise_for_status()
            self._refresh_devices()
        except requests.RequestException as exc:
            QMessageBox.warning(self, "언페어링 실패", str(exc))

    def _purge_revoked_devices(self):
        try:
            response = requests.delete(f"{self.base_url}/remote/devices/revoked", timeout=5)
            response.raise_for_status()
            removed = response.json().get("removed", 0)
            self.pairing_status_label.setText(f"폐기된 기기 {removed}개를 정리했습니다.")
            self._refresh_devices()
        except requests.RequestException as exc:
            QMessageBox.warning(self, "기기 정리 실패", str(exc))

    def _refresh_tailscale(self):
        self.tailscale_summary_label.setText("Tailscale: 확인 중...")
        self.tailscale_health_text.setPlainText("Tailscale 상태를 불러오는 중...")
        def task():
            response = requests.get(f"{self.base_url}/remote/readiness", timeout=5)
            response.raise_for_status()
            return response.json().get("tailscale_readiness", {})
        self._start_worker("tailscale", task)

    def _apply_tailscale_payload(self, tailscale: dict) -> None:
        color = tailscale.get("color") or "unknown"
        state = tailscale.get("state") or "unknown"
        foundation_state = tailscale.get("foundation_state") or "unknown"
        message = tailscale.get("message") or "tailscale 상태 미확인"
        self.tailscale_summary_label.setText(f"Tailscale: {foundation_state} · {message}")
        self.tailscale_health_text.setPlainText(
            "Tailscale readiness\n"
            f"- state: {state}\n"
            f"- foundation_state: {foundation_state}\n"
            f"- color: {color}\n"
            f"- message: {message}\n"
            f"- suggested_base_urls: {tailscale.get('suggested_base_urls')}\n"
            f"- details: {tailscale.get('details')}\n"
        )

    def _ensure_tailscale(self):
        self.tailscale_summary_label.setText("Tailscale: 설치/실행 확인 중...")
        self.tailscale_health_text.setPlainText("설치/실행 확인은 시간이 걸릴 수 있습니다. 창은 계속 사용할 수 있습니다.")
        def task():
            response = requests.post(f"{self.base_url}/remote/tailscale/ensure", timeout=30)
            response.raise_for_status()
            return response.json()
        self._start_worker("tailscale_ensure", task)

    def _apply_tailscale_ensure_payload(self, payload: dict) -> None:
        self.tailscale_summary_label.setText(f"Tailscale: {'ready' if payload.get('ready') else 'not ready'} · {payload.get('message')}")
        self.tailscale_health_text.setPlainText(str(payload))

    def _tailscale_up(self):
        self.tailscale_summary_label.setText("Tailscale: 활성화 중...")
        self.tailscale_health_text.setPlainText("설치된 Tailscale CLI 경로를 찾아 tailscale up --accept-routes를 실행합니다.")
        def task():
            response = requests.post(f"{self.base_url}/remote/tailscale/up", timeout=45)
            response.raise_for_status()
            return response.json()
        self._start_worker("tailscale_up", task)

    def _tailscale_down(self):
        self.tailscale_summary_label.setText("Tailscale: 비활성화 중...")
        self.tailscale_health_text.setPlainText("호스트 로컬에서 tailscale down을 실행해 Tailscale 네트워크만 비활성화합니다. 설치 제거는 하지 않습니다.")
        def task():
            response = requests.post(f"{self.base_url}/remote/tailscale/down", timeout=30)
            response.raise_for_status()
            return response.json()
        self._start_worker("tailscale_down", task)

    def _apply_tailscale_control_payload(self, payload: dict) -> None:
        after = payload.get("after") if isinstance(payload.get("after"), dict) else {}
        state = after.get("foundation_state") or after.get("state") or ("ready" if payload.get("ready") else "unknown")
        self.tailscale_summary_label.setText(f"Tailscale: {state} · {payload.get('message')}")
        self.tailscale_health_text.setPlainText(str(payload))

    def _refresh_power_setup(self):
        self.power_status_label.setText("전원 준비: 확인 중...")
        self.power_setup_text.setPlainText("호스트 전원 준비 상태를 불러오는 중...")
        def task():
            response = requests.get(f"{self.base_url}/remote/power/setup", timeout=5)
            response.raise_for_status()
            return response.json()
        self._start_worker("power", task)

    def _apply_power_setup_payload(self, payload: dict) -> None:
        ssh_service = payload.get("ssh_service") or {}
        firewall = payload.get("firewall") or {}
        self.power_status_label.setText(payload.get("message") or "전원 준비 상태 확인 완료")
        self.power_setup_text.setPlainText(
            "호스트 전원 준비 상태\n"
            f"- host: {payload.get('host_platform')} / user: {payload.get('user')}\n"
            f"- authorized_keys: {payload.get('effective_authorized_keys_path') or payload.get('authorized_keys_path')} (exists={payload.get('authorized_keys_exists')})\n"
            f"- SSH scope: {payload.get('authorized_keys_scope') or 'user'}"
            f"{' / Administrators' if payload.get('administrators_authorized_keys_active') else ''}\n"
            f"- OpenSSH Server: running={ssh_service.get('running')} start_type={ssh_service.get('start_type')} message={ssh_service.get('message')}\n"
            f"- Firewall: enabled={firewall.get('enabled')} message={firewall.get('message')}\n"
            "클라이언트가 SmartThings/OpenSSH 직접 경로로 전원 제어를 수행합니다. "
            "SSH public key 등록은 페어링한 클라이언트의 자동 설정 흐름이 수행합니다."
        )

class NumericTableWidgetItem(QTableWidgetItem):
    """ QTableWidgetItem that allows numeric sorting. """
    def __lt__(self, other: QTableWidgetItem) -> bool:
        try:
            return float(self.text()) < float(other.text())
        except ValueError:
            return super().__lt__(other)

class RunningProcessSelectionDialog(QDialog):
    """ Dialog to select a running process from a list. """
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("실행 중인 프로세스 선택")
        self.selected_process_info: Optional[Dict[str, Any]] = None

        self.setMinimumSize(750, 500)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("현재 실행 중인 프로세스 목록 (컬럼 헤더 클릭 시 정렬):"))

        self.process_list_widget = QTableWidget()
        self.process_list_widget.setColumnCount(6)
        self.process_list_widget.setHorizontalHeaderLabels(["", "PID", "이름", "실행 파일 경로", "메모리(MB)", "CPU(%)"])
        self.process_list_widget.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.process_list_widget.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.process_list_widget.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.process_list_widget.setSortingEnabled(True)

        header = self.process_list_widget.horizontalHeader()
        if header:  # None 체크 추가
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents) # Icon
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents) # PID
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)      # Name
            header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)          # Path
            header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents) # Memory
            header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents) # CPU

        self.process_list_widget.setColumnWidth(0, 32) # Icon column width
        self.process_list_widget.setColumnWidth(2, 200) # Name column initial width
        layout.addWidget(self.process_list_widget)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        layout.addWidget(self.button_box)

        # Connections
        self.process_list_widget.doubleClicked.connect(self.accept)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

        self.populate_running_processes()

    def populate_running_processes(self):
        """ Fetches and displays currently running processes in the table. """
        self.process_list_widget.setSortingEnabled(False)
        processes = get_all_running_processes_info() # External function
        self.process_list_widget.setRowCount(len(processes))

        for row, proc_info in enumerate(processes):
            q_icon = proc_info.get('q_icon')
            pid_val = proc_info.get('pid', 0)
            name_val = proc_info.get('name', 'N/A')
            exe_val = proc_info.get('exe', 'N/A')
            mem_val_mb = proc_info.get('memory_rss_mb', 0.0)
            cpu_val_percent = proc_info.get('cpu_percent', 0.0)

            icon_item = QTableWidgetItem()
            if q_icon and not q_icon.isNull(): # q_icon is QIcon from process_utils
                icon_item.setIcon(q_icon)

            pid_item = NumericTableWidgetItem(str(pid_val))
            name_item = QTableWidgetItem(name_val)
            exe_item = QTableWidgetItem(exe_val)
            mem_item = NumericTableWidgetItem(f"{mem_val_mb:.1f}")
            cpu_item = NumericTableWidgetItem(f"{cpu_val_percent:.1f}")

            name_item.setData(Qt.ItemDataRole.UserRole, proc_info)

            self.process_list_widget.setItem(row, 0, icon_item)
            self.process_list_widget.setItem(row, 1, pid_item)
            self.process_list_widget.setItem(row, 2, name_item)
            self.process_list_widget.setItem(row, 3, exe_item)
            self.process_list_widget.setItem(row, 4, mem_item)
            self.process_list_widget.setItem(row, 5, cpu_item)

        self.process_list_widget.setSortingEnabled(True)
        self.process_list_widget.sortByColumn(4, Qt.SortOrder.DescendingOrder) # Sort by Memory

    def accept(self):
        """ Overrides QDialog.accept() to store selected process info. """
        selection_model = self.process_list_widget.selectionModel()
        if selection_model:  # None 체크 추가
            selected_rows = selection_model.selectedRows()
            if selected_rows:
                selected_row_index = selected_rows[0].row()
                item_with_data = self.process_list_widget.item(selected_row_index, 2) # Name item
                if item_with_data:
                    self.selected_process_info = item_with_data.data(Qt.ItemDataRole.UserRole)
        super().accept()

    def get_selected_process_info(self) -> Optional[Dict[str, Any]]:
        """ Returns the dictionary of the selected process. """
        return self.selected_process_info

class ProcessDialog(QDialog):
    """ Dialog for adding a new process or editing an existing one. """
    def __init__(self, parent: Optional[QWidget] = None, existing_process: Optional[ManagedProcess] = None):
        super().__init__(parent)
        self.existing_process = existing_process

        if self.existing_process:
            self.setWindowTitle("프로세스 편집")
        else:
            self.setWindowTitle("새 프로세스 추가")

        self.setMinimumWidth(450)
        self.form_layout = QFormLayout(self)  # 변수명 변경

        self.select_running_button = QPushButton("실행 중인 프로세스에서 자동 완성...")
        self.name_edit = QLineEdit()
        self.monitoring_path_edit = QLineEdit()
        self.monitoring_path_button = QPushButton("찾아보기...")
        self.launch_path_edit = QLineEdit()
        self.launch_path_button = QPushButton("찾아보기...")
        self.server_reset_time_edit = QLineEdit()
        self.user_cycle_hours_edit = QLineEdit()
        self.mandatory_times_edit = QLineEdit()
        self.is_mandatory_time_enabled_checkbox = QCheckBox("특정 접속 시간 알림 활성화")

        self.form_layout.addRow(self.select_running_button)

        # --- 프리셋 선택 섹션 추가 ---
        self._setup_preset_section()

        self.form_layout.addRow("이름 (비워두면 자동 생성):", self.name_edit)

        monitor_path_layout = QHBoxLayout()
        monitor_path_layout.addWidget(self.monitoring_path_edit)
        monitor_path_layout.addWidget(self.monitoring_path_button)
        self.form_layout.addRow("모니터링 경로 (필수):", monitor_path_layout)

        launch_path_layout = QHBoxLayout()
        launch_path_layout.addWidget(self.launch_path_edit)
        launch_path_layout.addWidget(self.launch_path_button)
        self.form_layout.addRow("실행 경로 (비워두면 모니터링 경로 사용):", launch_path_layout)

        self.form_layout.addRow("서버 초기화 시각 (HH:MM):", self.server_reset_time_edit)
        self.form_layout.addRow("사용자 실행 주기 (시간):", self.user_cycle_hours_edit)
        self.form_layout.addRow("특정 접속 시각 (HH:MM, 쉼표로 구분):", self.mandatory_times_edit)
        self.form_layout.addRow(self.is_mandatory_time_enabled_checkbox)

        # 실행 방식 선택 섹션
        self._setup_launch_type_section()

        # 스태미나 추적 섹션 (호요버스 게임 전용)
        self._setup_stamina_section()

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.form_layout.addRow(self.button_box)

        self.select_running_button.clicked.connect(self.open_running_process_selector)
        self.monitoring_path_button.clicked.connect(
            lambda: self.browse_file(self.monitoring_path_edit)
        )
        self.launch_path_button.clicked.connect(
            lambda: self.browse_file(self.launch_path_edit)
        )
        self.button_box.accepted.connect(self.accept_data)
        self.button_box.rejected.connect(self.reject)

        # 실행 방식 선택 콤보박스 활성화 상태 업데이트 (경로 변경 시)
        self.monitoring_path_edit.textChanged.connect(self._update_launch_type_enabled)
        self.launch_path_edit.textChanged.connect(self._update_launch_type_enabled)

        if self.existing_process:
            self.populate_fields_from_existing_process()

    def _setup_preset_section(self):
        """프리셋 선택 및 저장 섹션 설정"""
        from src.utils.game_preset_manager import GamePresetManager

        preset_layout = QHBoxLayout()
        preset_layout.addWidget(QLabel("프리셋:"))

        self.preset_combo = QComboBox()
        self.preset_combo.addItem("선택 안 함", None)

        # 프리셋 목록 로드
        try:
            self.preset_manager = GamePresetManager()
            presets = self.preset_manager.get_all_presets()

            # 정렬: 시스템 프리셋 먼저, 그 다음 이름순
            # (여기서는 간단히 이름순으로 정렬하되, 원본 순서도 고려할 수 있음)
            presets.sort(key=lambda p: p.get("display_name", ""))

            for preset in presets:
                display_name = preset.get("display_name", "Unknown")
                preset_id = preset.get("id")
                # 사용자 정의 프리셋 표시
                if not preset_id:
                     continue
                self.preset_combo.addItem(display_name, preset)


        except Exception as e:
            logger.warning(f"프리셋 로드 실패: {e}")

        preset_layout.addWidget(self.preset_combo, 1) # 늘어나도록 설정

        # 적용 버튼
        self.apply_preset_button = QPushButton("적용")
        self.apply_preset_button.setToolTip("선택한 프리셋의 설정을 현재 입력창에 적용합니다.")
        self.apply_preset_button.clicked.connect(self._on_apply_preset_clicked)
        preset_layout.addWidget(self.apply_preset_button)

        # 현재 설정을 프리셋으로 저장 버튼 (신규 추가 모드로 프리셋 에디터 열기)
        self.save_as_preset_button = QPushButton("현재 설정을 프리셋으로 저장")
        self.save_as_preset_button.setToolTip("현재 입력된 설정값으로 새 프리셋을 등록합니다.")
        self.save_as_preset_button.clicked.connect(self._on_save_as_preset_clicked)
        preset_layout.addWidget(self.save_as_preset_button)

        # 프리셋 관리 버튼 (목록 보기/편집)
        self.manage_presets_button = QPushButton("프리셋 관리...")
        self.manage_presets_button.setToolTip("기존 프리셋 목록을 확인하고 편집합니다.")
        self.manage_presets_button.clicked.connect(self._open_preset_manager)
        preset_layout.addWidget(self.manage_presets_button)

        self.form_layout.addRow(preset_layout)

    def _open_preset_manager(self):
        """프리셋 관리자 열기"""
        from src.gui.preset_editor_dialog import PresetEditorDialog
        dialog = PresetEditorDialog(self)

        # 프리셋 변경 시 메인 윈도우 새로고침
        def on_presets_changed():
            # MainWindow 찾기 (ProcessDialog의 parent 체인을 따라 올라감)
            main_window = self.parent()
            while main_window and not hasattr(main_window, 'refresh_presets_and_ui'):
                main_window = main_window.parent()

            if main_window and hasattr(main_window, 'refresh_presets_and_ui'):
                main_window.refresh_presets_and_ui()

        dialog.presets_changed.connect(on_presets_changed)
        dialog.exec()
        self._refresh_preset_combo()

    def _on_save_as_preset_clicked(self):
        """현재 설정을 신규 프리셋으로 바로 저장 (간단한 입력 다이얼로그)"""
        from PyQt6.QtWidgets import QInputDialog, QLineEdit
        from src.utils.game_preset_manager import GamePresetManager
        import re
        import os

        # 현재 입력값 수집
        name = self.name_edit.text().strip()
        exe_path = self.monitoring_path_edit.text().strip()
        reset_time = self.server_reset_time_edit.text().strip()
        cycle_hours = self.user_cycle_hours_edit.text().strip()
        mandatory_times = self.mandatory_times_edit.text().strip()
        launch_type = self.launch_type_combo.currentData() if hasattr(self, 'launch_type_combo') else "shortcut"

        # 1. 프리셋 ID 입력 (신규)
        manager = GamePresetManager()
        preset_id = None
        while True:
            preset_id, ok = QInputDialog.getText(
                self,
                "프리셋 ID",
                "프리셋 ID를 입력하세요 (영문 소문자, 숫자, 언더스코어만):",
                QLineEdit.EchoMode.Normal
            )
            if not ok:
                return

            preset_id = preset_id.strip().lower()

            # ID 유효성 검사
            if not re.match(r'^[a-z0-9_]+$', preset_id):
                QMessageBox.warning(
                    self, "입력 오류",
                    "ID는 영문 소문자, 숫자, 언더스코어만 사용할 수 있습니다."
                )
                continue

            # 중복 ID 체크
            if manager.get_preset_by_id(preset_id):
                reply = QMessageBox.question(
                    self, "ID 중복",
                    f"'{preset_id}' ID가 이미 존재합니다. 덮어쓰시겠습니까?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.No:
                    continue

            break  # 유효한 ID 입력 완료

        # 2. 프리셋 표시 이름 입력 (기존 로직)
        if not name:
            name, ok = QInputDialog.getText(
                self, "프리셋 이름", "프리셋 표시 이름을 입력하세요:"
            )
            if not ok or not name.strip():
                return
            name = name.strip()

        # 3. 실행 파일 패턴 입력 (기본값: 모니터링 경로의 파일명)
        default_exe = os.path.basename(exe_path) if exe_path else ""
        exe_pattern, ok = QInputDialog.getText(
            self,
            "실행 파일 패턴",
            "프리셋을 인식할 실행 파일 이름을 입력하세요:\n(예: game.exe)",
            QLineEdit.EchoMode.Normal,
            default_exe
        )
        if not ok or not exe_pattern.strip():
            QMessageBox.warning(self, "취소됨", "실행 파일 패턴은 필수입니다.")
            return
        exe_pattern = exe_pattern.strip()

        # mandatory_times 파싱
        mandatory_times_list = []
        if mandatory_times:
            mandatory_times_list = [t.strip() for t in mandatory_times.split(",") if t.strip()]

        # cycle_hours 파싱
        cycle_hours_int = None
        if cycle_hours:
            try:
                cycle_hours_int = int(cycle_hours)
            except ValueError:
                pass

        # 자원 추적 설정
        tracking_target = self.hoyolab_game_combo.currentData() if hasattr(self, 'hoyolab_game_combo') else None
        tracking_enabled = bool(
            hasattr(self, 'stamina_tracking_checkbox')
            and self.stamina_tracking_checkbox.isChecked()
            and tracking_target is not None
        )
        is_hoyoverse = tracking_enabled and tracking_target in {"honkai_starrail", "zenless_zone_zero"}
        hoyolab_game_id = tracking_target if is_hoyoverse else None
        resource_tracking_enabled = tracking_enabled and tracking_target == "nikke_outpost_storage"
        resource_provider = "nikke_blablalink" if resource_tracking_enabled else None
        resource_key = "nikke_outpost_storage" if resource_tracking_enabled else None
        resource_label = NIKKE_OUTPOST_LABEL if resource_tracking_enabled else None

        # 프리셋 데이터 구성 (모든 필드 명시적 포함)
        preset_data = {
            # 기본 필드
            "id": preset_id,
            "display_name": name,
            "exe_patterns": [exe_pattern],
            "is_hoyoverse": is_hoyoverse,
            "preferred_launch_type": launch_type,
            "mandatory_times": mandatory_times_list,

            # 아이콘 (사용자가 직접 설정할 수 없으므로 null)
            "icon_path": None,
            "icon_type": None,

            # 호요버스/게임 설정
            "hoyolab_game_id": hoyolab_game_id if is_hoyoverse else None,
            "server_reset_time": reset_time if reset_time else None,
            "default_cycle_hours": cycle_hours_int,
            "stamina_name": None,
            "stamina_max_default": None,
            "stamina_recovery_minutes": None,
            "launcher_patterns": None,
            "resource_tracking_enabled": resource_tracking_enabled,
            "resource_provider": resource_provider,
            "resource_key": resource_key,
            "resource_label": resource_label
        }

        # 4. 프리셋 저장
        try:
            # 중복 ID는 이미 위에서 확인하여 덮어쓰기 동의를 받았으므로 바로 저장
            existing = manager.get_preset_by_id(preset_id)
            if existing:
                success = manager.update_user_preset(preset_id, preset_data)
            else:
                success = manager.add_user_preset(preset_data)

            if success:
                QMessageBox.information(
                    self,
                    "저장 완료",
                    f"프리셋 '{name}'이(가) 저장되었습니다."
                )
                self._refresh_preset_combo()
            else:
                QMessageBox.critical(self, "저장 실패", "프리셋 저장에 실패했습니다.")
        except Exception as e:
            QMessageBox.critical(self, "오류", f"프리셋 저장 중 오류 발생:\n{str(e)}")

    def _on_apply_preset_clicked(self):
        """선택한 프리셋 적용"""
        preset = self.preset_combo.currentData()
        if not preset:
            return

        reply = QMessageBox.question(
            self,
            "프리셋 적용",
            f"프리셋 '{preset.get('display_name')}' 설정을 적용하시겠습니까?\n"
            "현재 입력된 내용이 덮어씌워질 수 있습니다.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            self._apply_preset_data(preset)
            QMessageBox.information(self, "적용 완료", "프리셋 설정이 적용되었습니다.")

    def _apply_preset_data(self, preset: Dict[str, Any]):
        """프리셋 데이터를 UI 필드에 적용"""
        # 이름 적용 (비어있거나 덮어쓰기)
        if hasattr(self, 'name_edit'):
            self.name_edit.setText(preset.get("display_name", ""))

        # 서버 초기화 시간
        if "server_reset_time" in preset:
            self.server_reset_time_edit.setText(preset["server_reset_time"])

        # 사용자 주기
        if "default_cycle_hours" in preset:
            self.user_cycle_hours_edit.setText(str(preset["default_cycle_hours"]))

        # [NEW] Mandatory Times
        if "mandatory_times" in preset and hasattr(self, 'mandatory_times_edit'):
            m_times = preset["mandatory_times"]
            if isinstance(m_times, list):
                self.mandatory_times_edit.setText(", ".join(m_times))
            else:
                self.mandatory_times_edit.setText(str(m_times))

        # [NEW] Launch Type
        if "preferred_launch_type" in preset and hasattr(self, 'launch_type_combo'):
            l_type = preset["preferred_launch_type"]
            idx = self.launch_type_combo.findData(l_type)
            if idx >= 0:
                self.launch_type_combo.setCurrentIndex(idx)

        # 스태미나/리소스 추적 대상 자동 선택
        selected_tracking_target = None
        if preset.get("is_hoyoverse", False) and preset.get("hoyolab_game_id"):
            selected_tracking_target = preset.get("hoyolab_game_id")
        elif (
            preset.get("resource_tracking_enabled")
            and preset.get("resource_provider") == "nikke_blablalink"
            and preset.get("resource_key") == "nikke_outpost_storage"
        ):
            selected_tracking_target = "nikke_outpost_storage"

        if hasattr(self, 'hoyolab_game_combo'):
            index = self.hoyolab_game_combo.findData(selected_tracking_target) if selected_tracking_target else 0
            self.hoyolab_game_combo.setCurrentIndex(index if index >= 0 else 0)
        if hasattr(self, 'stamina_tracking_checkbox'):
            self.stamina_tracking_checkbox.setChecked(bool(selected_tracking_target))

    # _on_save_as_preset_clicked 메서드는 위에서 재정의됨 (직접 코드 삭제 대신 위쪽 청크에서 덮어쓰거나 빈 메서드로 대체 필요하지만,
    # multi_replace는 덮어쓰기이므로, 기존 _on_save_as_preset_clicked 메서드 전체를 이 청크로 대체하는 게 나을 수도 있음.
    # 하지만 여기서는 _apply_preset_data 뒤에 오는 _on_save_as_preset_clicked를 제거해야 함.
    # 해당 메서드는 파일 뒷부분에 있음.
    # 차라리 별도 청크로 삭제 처리.

    def _refresh_preset_combo(self):
        """프리셋 콤보박스 목록 갱신"""
        current_data = self.preset_combo.currentData()

        self.preset_combo.clear()
        self.preset_combo.addItem("선택 안 함", None)

        self.preset_manager.reload()
        presets = self.preset_manager.get_all_presets()
        presets.sort(key=lambda p: p.get("display_name", ""))

        for preset in presets:
            display_name = preset.get("display_name", "Unknown")
            preset_id = preset.get("id")
            if not preset_id: continue
            self.preset_combo.addItem(display_name, preset)

        # 이전에 선택했던 항목 복구 시도
        if current_data:
            index = self.preset_combo.findData(current_data)
            if index >= 0:
                self.preset_combo.setCurrentIndex(index)

    def _setup_launch_type_section(self):
        """실행 방식 선택 섹션 설정"""
        launch_type_layout = QHBoxLayout()
        launch_type_layout.addWidget(QLabel("실행 방식:"))

        self.launch_type_combo = QComboBox()
        self.launch_type_combo.addItem("바로가기 선호 (기본)", "shortcut")
        self.launch_type_combo.addItem("프로세스 선호", "direct")
        self.launch_type_combo.setToolTip(
            "모니터링 경로와 실행 경로가 다를 때 기본 실행 대상을 선택합니다.\n"
            "• 바로가기 선호: 실행 경로(바로가기)를 우선 사용, 없으면 모니터링 경로 사용\n"
            "• 프로세스 선호: 모니터링 경로(실행 파일)를 우선 사용, 없으면 실행 경로 사용"
        )
        launch_type_layout.addWidget(self.launch_type_combo)
        launch_type_layout.addStretch()

        self.form_layout.addRow(launch_type_layout)

        # 초기 상태 설정 (비활성화 - 경로가 같으면)
        # 시그널 연결은 모든 위젯 초기화 후에 한 번만 하도록 __init__ 마지막에서 처리
        self._update_launch_type_enabled()

    def _update_launch_type_enabled(self, _=None):
        """모니터링 경로와 실행 경로가 다를 때만 실행 방식 선택 활성화"""
        # 콤보박스가 아직 생성되지 않은 경우 무시
        if not hasattr(self, 'launch_type_combo'):
            return

        monitoring = self.monitoring_path_edit.text().strip()
        launch = self.launch_path_edit.text().strip()

        # 실행 경로가 비어있거나 모니터링 경로와 같으면 비활성화
        is_different = bool(launch and monitoring != launch)
        self.launch_type_combo.setEnabled(is_different)


    def _setup_stamina_section(self):
        """스태미나 추적 섹션 설정 (호요버스 게임 전용)"""
        self.stamina_group_box = QGroupBox("스태미나/리소스 자동 추적")
        stamina_layout = QVBoxLayout()

        # 스태미나 자동 추적 활성화 체크박스
        self.stamina_tracking_checkbox = QCheckBox("스태미나 자동 추적 활성화")
        self.stamina_tracking_checkbox.setToolTip(
            "게임 종료 시 HoYoLab 또는 BlablaLink API를 통해 스태미나/리소스를 자동으로 조회합니다."
        )
        self.stamina_tracking_checkbox.toggled.connect(self._on_stamina_tracking_toggled)
        stamina_layout.addWidget(self.stamina_tracking_checkbox)

        # 호요버스 게임 선택 콤보박스
        hoyolab_game_layout = QHBoxLayout()
        hoyolab_game_layout.addWidget(QLabel("추적 대상:"))
        self.hoyolab_game_combo = QComboBox()
        self.hoyolab_game_combo.addItem("(없음)", None)
        self.hoyolab_game_combo.addItem("붕괴: 스타레일", "honkai_starrail")
        self.hoyolab_game_combo.addItem("젠레스 존 제로", "zenless_zone_zero")
        self.hoyolab_game_combo.addItem(f"NIKKE - {NIKKE_OUTPOST_LABEL}", "nikke_outpost_storage")
        self.hoyolab_game_combo.setToolTip("추적할 HoYoLab 스태미나 또는 NIKKE ShiftyPad 리소스를 선택하세요.")
        hoyolab_game_layout.addWidget(self.hoyolab_game_combo)
        hoyolab_game_layout.addStretch()
        stamina_layout.addLayout(hoyolab_game_layout)

        # 스태미나 조회 테스트 버튼
        self.stamina_test_button = QPushButton("조회 테스트")
        self.stamina_test_button.setToolTip("HoYoLab/BlablaLink API 연결을 테스트하고 현재 값을 조회합니다.")
        self.stamina_test_button.clicked.connect(self._test_stamina_connection)
        stamina_layout.addWidget(self.stamina_test_button)

        self.stamina_group_box.setLayout(stamina_layout)
        self.form_layout.addRow(self.stamina_group_box)

        # 초기 상태: 체크박스 상태에 따라 콤보박스 활성화
        self._on_stamina_tracking_toggled(False)

    def _on_stamina_tracking_toggled(self, checked: bool):
        """스태미나 추적 체크박스 상태 변경 시"""
        if checked:
            # 체크박스 활성화 시 콤보박스 활성화
            self.hoyolab_game_combo.setEnabled(True)
        else:
            # 체크박스 비활성화 시 콤보박스를 '(없음)'으로 설정하고 비활성화
            self.hoyolab_game_combo.setCurrentIndex(0)  # '(없음)' 선택
            self.hoyolab_game_combo.setEnabled(False)

    def _test_stamina_connection(self):
        """스태미나 조회 테스트"""
        # 호요랩 게임 콤보박스에서 선택된 게임 사용
        game_id = self.hoyolab_game_combo.currentData()
        if not game_id:
            QMessageBox.warning(self, "오류", "추적 대상을 선택해주세요.")
            return

        if game_id == "nikke_outpost_storage":
            self._test_nikke_resource_connection()
            return

        try:
            from src.services.hoyolab import get_hoyolab_service

            service = get_hoyolab_service()

            # 라이브러리 확인
            if not service.is_available():
                QMessageBox.warning(
                    self,
                    "라이브러리 없음",
                    "HoYoLab API 연동을 위한 genshin.py 라이브러리가 설치되지 않았습니다.\n\n"
                    "설치 방법: pip install genshin"
                )
                return

            # 인증 정보 확인
            if not service.is_configured():
                reply = QMessageBox.question(
                    self,
                    "인증 정보 없음",
                    "HoYoLab 인증 정보가 설정되지 않았습니다.\n"
                    "지금 설정하시겠습니까?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes
                )
                if reply == QMessageBox.StandardButton.Yes:
                    from src.gui.dialogs import HoYoLabSettingsDialog
                    dialog = HoYoLabSettingsDialog(self)
                    dialog.exec()
                    # 설정 후 다시 확인
                    if not service.is_configured():
                        return
                else:
                    return

            # 스태미나 조회
            game_names = {
                "honkai_starrail": "붕괴: 스타레일",
                "zenless_zone_zero": "젠레스 존 제로"
            }
            game_name = game_names.get(game_id, game_id)

            # 커서를 대기 커서로 변경
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            QApplication.processEvents()  # UI 업데이트

            try:
                stamina_info = service.get_stamina(game_id)

                if stamina_info:
                    full_time_str = ""
                    if stamina_info.full_time:
                        full_time_str = f"\n완전 회복 예상: {stamina_info.full_time.strftime('%Y-%m-%d %H:%M:%S')}"

                    stamina_name = "개척력" if game_id == "honkai_starrail" else "배터리"

                    # 편집 모드인 경우 프로세스에 스태미나 정보 즉시 저장
                    save_result = ""
                    if self.existing_process:
                        try:
                            # 로컬 객체 업데이트
                            self.existing_process.stamina_current = stamina_info.current
                            self.existing_process.stamina_max = stamina_info.max
                            self.existing_process.stamina_updated_at = stamina_info.updated_at.timestamp()

                            # API를 통해 스태미나 런타임 필드만 업데이트
                            parent_window = self.parent()
                            if parent_window and hasattr(parent_window, 'data_manager'):
                                updater = getattr(parent_window.data_manager, 'update_process_stamina', None)
                                result = bool(updater and updater(
                                    self.existing_process.id,
                                    stamina_info.current,
                                    stamina_info.max,
                                    stamina_info.updated_at.timestamp(),
                                ))
                                if result:
                                    save_result = "\n\n💾 스태미나 정보가 저장되었습니다."
                                    # GUI 새로고침
                                    if hasattr(parent_window, 'populate_process_list'):
                                        parent_window.populate_process_list()
                                else:
                                    save_result = "\n\n⚠️ 스태미나 정보 저장 실패"
                            else:
                                save_result = "\n\n💾 스태미나 정보가 임시 저장되었습니다."
                        except Exception as e:
                            logger.error(f"스태미나 저장 오류: {e}", exc_info=True)
                            save_result = f"\n\n⚠️ 저장 오류: {e}"
                    else:
                        save_result = "\n\nℹ️ 프로세스 저장 시 함께 저장됩니다."

                    QMessageBox.information(
                        self,
                        "스태미나 조회 성공",
                        f"✅ {game_name} 스태미나 조회 성공!\n\n"
                        f"{stamina_name}: {stamina_info.current} / {stamina_info.max}\n"
                        f"회복까지: {stamina_info.recover_time // 60}분{full_time_str}\n"
                        f"조회 시각: {stamina_info.updated_at.strftime('%Y-%m-%d %H:%M:%S')}"
                        f"{save_result}"
                    )
                else:
                    QMessageBox.warning(
                        self,
                        "조회 실패",
                        f"❌ {game_name} 스태미나 조회에 실패했습니다.\n\n"
                        "가능한 원인:\n"
                        "• HoYoLab 쿠키가 만료되었습니다.\n"
                        "• 해당 게임을 플레이하지 않았습니다.\n"
                        "• API 서버에 문제가 있습니다.\n\n"
                        "자원 추적 설정에서 쿠키를 다시 설정해보세요."
                    )
            except Exception as e:
                QMessageBox.warning(
                    self,
                    "오류",
                    f"스태미나 조회 중 오류가 발생했습니다:\n{str(e)}"
                )
            finally:
                # 커서를 원래대로 복원
                QApplication.restoreOverrideCursor()

        except ImportError:
            QMessageBox.warning(
                self,
                "모듈 없음",
                "HoYoLab 서비스 모듈을 찾을 수 없습니다."
            )
        except Exception as e:
            QMessageBox.warning(
                self,
                "오류",
                f"스태미나 테스트 중 오류가 발생했습니다:\n{str(e)}"
            )

    def _test_nikke_resource_connection(self):
        """NIKKE ShiftyPad 전초기지 방어 보상 조회 테스트."""
        try:
            from src.services.nikke import get_nikke_service, NIKKE_OUTPOST_LABEL

            service = get_nikke_service()
            if not service.is_configured():
                reply = QMessageBox.question(
                    self,
                    "인증 정보 없음",
                    "BlablaLink/NIKKE 인증 정보가 설정되지 않았습니다.\n"
                    "자원 추적 설정을 여시겠습니까?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )
                if reply == QMessageBox.StandardButton.Yes:
                    from src.gui.dialogs import HoYoLabSettingsDialog

                    dialog = HoYoLabSettingsDialog(self)
                    dialog.exec()
                    if not service.is_configured():
                        return
                else:
                    return

            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            QApplication.processEvents()
            try:
                snapshot = service.get_outpost_storage()
                if snapshot.status == "ok" and snapshot.percent is not None:
                    save_result = ""
                    if self.existing_process:
                        self.existing_process.resource_tracking_enabled = True
                        self.existing_process.resource_provider = snapshot.provider
                        self.existing_process.resource_key = snapshot.resource_key
                        self.existing_process.resource_label = snapshot.label
                        self.existing_process.resource_percent = snapshot.percent
                        self.existing_process.resource_updated_at = snapshot.updated_at.timestamp()
                        self.existing_process.resource_status = snapshot.status
                        parent_window = self.parent()
                        if parent_window and hasattr(parent_window, "data_manager"):
                            updater = getattr(parent_window.data_manager, "update_process_resource", None)
                            if updater and updater(
                                self.existing_process.id,
                                snapshot.percent,
                                snapshot.updated_at.timestamp(),
                                snapshot.status,
                                snapshot.label,
                            ):
                                save_result = "\n\n💾 리소스 정보가 저장되었습니다."
                                if hasattr(parent_window, "populate_process_list"):
                                    parent_window.populate_process_list()
                            else:
                                save_result = "\n\n⚠️ 리소스 정보 저장 실패"
                        else:
                            save_result = "\n\n💾 리소스 정보가 임시 저장되었습니다."
                    else:
                        save_result = "\n\nℹ️ 프로세스 저장 시 함께 저장됩니다."

                    QMessageBox.information(
                        self,
                        "NIKKE 리소스 조회 성공",
                        f"✅ {NIKKE_OUTPOST_LABEL} 조회 성공!\n\n"
                        f"{NIKKE_OUTPOST_LABEL}: {snapshot.percent:.1f}%\n"
                        f"조회 시각: {snapshot.updated_at.strftime('%Y-%m-%d %H:%M:%S')}"
                        f"{save_result}",
                    )
                else:
                    QMessageBox.warning(
                        self,
                        "조회 실패",
                        "❌ NIKKE 전초기지 방어 보상 조회에 실패했습니다.\n\n"
                        f"상태: {snapshot.status}\n"
                        f"메시지: {snapshot.message or 'BlablaLink 세션/대표 계정 상태를 확인하세요.'}",
                    )
            finally:
                QApplication.restoreOverrideCursor()
        except Exception as e:
            QMessageBox.warning(self, "오류", f"NIKKE 리소스 테스트 중 오류가 발생했습니다:\n{str(e)}")

    def populate_fields_from_existing_process(self):
        if not self.existing_process:
            return
        self.name_edit.setText(self.existing_process.name)
        self.monitoring_path_edit.setText(self.existing_process.monitoring_path)
        self.launch_path_edit.setText(self.existing_process.launch_path)
        if self.existing_process.server_reset_time_str:
            self.server_reset_time_edit.setText(self.existing_process.server_reset_time_str)
        if self.existing_process.user_cycle_hours is not None:
            self.user_cycle_hours_edit.setText(str(self.existing_process.user_cycle_hours))
        if self.existing_process.mandatory_times_str:
            self.mandatory_times_edit.setText(",".join(self.existing_process.mandatory_times_str))
        self.is_mandatory_time_enabled_checkbox.setChecked(self.existing_process.is_mandatory_time_enabled)

        # 실행 방식 선택 로드
        if hasattr(self.existing_process, 'preferred_launch_type'):
            launch_type = self.existing_process.preferred_launch_type
            if launch_type == "auto":
                launch_type = "shortcut"
            for i in range(self.launch_type_combo.count()):
                if self.launch_type_combo.itemData(i) == launch_type:
                    self.launch_type_combo.setCurrentIndex(i)
                    break
            # 활성화 상태 업데이트
            self._update_launch_type_enabled()

        # 프리셋 자동 선택
        if hasattr(self.existing_process, 'user_preset_id') and self.existing_process.user_preset_id:
            for i in range(self.preset_combo.count()):
                preset_data = self.preset_combo.itemData(i)
                if preset_data and preset_data.get("id") == self.existing_process.user_preset_id:
                    self.preset_combo.setCurrentIndex(i)
                    logger.debug(f"프리셋 자동 선택: {self.existing_process.user_preset_id}")
                    break

        # 추적 대상 로드 (체크박스보다 먼저 설정)
        selected_tracking_target = None
        if getattr(self.existing_process, 'resource_provider', None) == 'nikke_blablalink' and getattr(self.existing_process, 'resource_key', None) == 'nikke_outpost_storage':
            selected_tracking_target = 'nikke_outpost_storage'
        elif hasattr(self.existing_process, 'hoyolab_game_id') and self.existing_process.hoyolab_game_id:
            selected_tracking_target = self.existing_process.hoyolab_game_id

        if selected_tracking_target:
            for i in range(self.hoyolab_game_combo.count()):
                if self.hoyolab_game_combo.itemData(i) == selected_tracking_target:
                    self.hoyolab_game_combo.setCurrentIndex(i)
                    break
        else:
            self.hoyolab_game_combo.setCurrentIndex(0)

        # 스태미나/리소스 추적 필드 로드 (콤보박스 설정 후 체크박스 설정)
        tracking_enabled = bool(
            getattr(self.existing_process, 'stamina_tracking_enabled', False)
            or getattr(self.existing_process, 'resource_tracking_enabled', False)
        )
        self.stamina_tracking_checkbox.setChecked(tracking_enabled)

        # 체크박스 상태에 따라 콤보박스 활성화/비활성화
        self._on_stamina_tracking_toggled(self.stamina_tracking_checkbox.isChecked())

    def open_running_process_selector(self):
        dialog = RunningProcessSelectionDialog(self) # Uses dialog defined above
        if dialog.exec():
            selected_info = dialog.get_selected_process_info()
            if selected_info:
                exe_path = selected_info.get('exe', '')
                proc_name_from_psutil = selected_info.get('name', '')
                base_name = os.path.basename(exe_path if exe_path else proc_name_from_psutil)
                default_name = os.path.splitext(base_name)[0]
                if not default_name and proc_name_from_psutil:
                    default_name = os.path.splitext(proc_name_from_psutil)[0]
                self.name_edit.setText(default_name or '')
                self.monitoring_path_edit.setText(exe_path)
                self.launch_path_edit.setText(exe_path)

                # 프리셋 자동 감지 및 적용 (GamePresetManager 사용)
                try:
                    from src.utils.game_preset_manager import GamePresetManager
                    manager = GamePresetManager()
                    preset = manager.detect_game_from_exe(exe_path)

                    if preset:
                        self._apply_preset_data(preset)
                        logger.debug(f"프리셋 '{preset.get('id')}' 자동 감지 및 적용 완료")
                except Exception as e:
                    logger.warning(f"프리셋 자동 적용 실패: {e}")

    def browse_file(self, path_edit_widget: QLineEdit):
        """ 파일 대화상자를 열어 파일을 선택하고, 선택된 파일의 경로를 입력 위젯에 설정합니다. """
        # 파일 필터 수정: .url 파일을 포함하도록 변경
        filters = [
            "모든 지원 파일 (*.exe *.bat *.cmd *.lnk *.url)", # 기본 필터
            "실행 파일 (*.exe *.bat *.cmd)",
            "바로 가기 (*.lnk *.url)", # .url을 바로 가기에 명시적으로 포함
            "모든 파일 (*)"
        ]
        filter_string = ";;".join(filters)

        # QFileDialog.getOpenFileName은 선택된 파일의 경로를 반환합니다.
        # .lnk나 .url 파일의 경우, 해당 파일 자체의 경로가 반환됩니다 (대상의 경로가 아님).
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "파일 선택",
            "",  # 시작 디렉토리 (비워두면 마지막 사용 디렉토리 또는 기본값)
            filter_string
        )
        if file_path:
            # 바로가기 파일인 경우 자동으로 복사
            file_ext = os.path.splitext(file_path)[1].lower()
            if file_ext in ['.lnk', '.url']:
                # 편집 모드일 때 기존 프로세스 ID 사용 (중복 방지)
                process_id = self.existing_process.id if self.existing_process else None
                copied_path = copy_shortcut_file(file_path, process_id)
                if copied_path:
                    # 복사된 파일 경로를 입력 필드에 설정
                    path_edit_widget.setText(copied_path)
                    QMessageBox.information(
                        self,
                        "바로가기 파일 복사 완료",
                        f"바로가기 파일이 자동으로 복사되었습니다.\n원본: {os.path.basename(file_path)}\n복사본: {os.path.basename(copied_path)}"
                    )
                else:
                    # 복사 실패 시 원본 경로 사용
                    path_edit_widget.setText(file_path)
                    QMessageBox.warning(
                        self,
                        "바로가기 파일 복사 실패",
                        f"바로가기 파일 복사에 실패했습니다. 원본 경로를 사용합니다.\n{file_path}"
                    )
            else:
                # 일반 실행 파일인 경우 원본 경로 그대로 사용
                path_edit_widget.setText(file_path)

    def validate_time_format(self, time_str: str) -> bool:
        if not time_str:
            return True
        try:
            datetime.datetime.strptime(time_str, "%H:%M")
            return True
        except ValueError:
            return False

    def accept_data(self):
        if not self.monitoring_path_edit.text().strip():
            QMessageBox.warning(self, "입력 오류", "모니터링 경로를 입력해야 합니다.")
            return

        reset_time_str = self.server_reset_time_edit.text().strip()
        if reset_time_str and not self.validate_time_format(reset_time_str):
            QMessageBox.warning(self, "입력 오류", f"서버 초기화 시각 형식이 잘못되었습니다 (HH:MM): {reset_time_str}")
            return

        cycle_hours_str = self.user_cycle_hours_edit.text().strip()
        if cycle_hours_str:
            try:
                int(cycle_hours_str)
            except ValueError:
                QMessageBox.warning(self, "입력 오류", f"사용자 실행 주기는 숫자로 입력해야 합니다: {cycle_hours_str}")
                return

        mandatory_times_list_str = self.mandatory_times_edit.text().strip()
        if mandatory_times_list_str:
            times = [t.strip() for t in mandatory_times_list_str.split(",")]
            for t_str in times:
                if t_str and not self.validate_time_format(t_str):
                    QMessageBox.warning(self, "입력 오류", f"특정 접속 시각 형식이 잘못되었습니다 (HH:MM): {t_str}")
                    return
        self.accept()

    def get_data(self) -> Optional[Dict[str, Any]]:
        name = self.name_edit.text().strip()
        monitoring_path = self.monitoring_path_edit.text().strip()
        if not monitoring_path:
            return None

        launch_path = self.launch_path_edit.text().strip()
        final_launch_path = launch_path if launch_path else monitoring_path
        server_reset_time_str = self.server_reset_time_edit.text().strip()
        server_reset_time = server_reset_time_str if server_reset_time_str else None
        user_cycle_hours_str = self.user_cycle_hours_edit.text().strip()
        user_cycle_hours: Optional[int] = None
        if user_cycle_hours_str:
            try:
                user_cycle_hours = int(user_cycle_hours_str)
            except ValueError:
                user_cycle_hours = None

        mandatory_times_raw = self.mandatory_times_edit.text().strip()
        mandatory_times_list: List[str] = []
        if mandatory_times_raw:
            mandatory_times_list = [t.strip() for t in mandatory_times_raw.split(",") if t.strip()]

        is_mandatory_enabled = self.is_mandatory_time_enabled_checkbox.isChecked()

        # 실행 방식 선택
        preferred_launch_type = self.launch_type_combo.currentData() or "shortcut"

        # 프리셋 ID 추출
        preset_data = self.preset_combo.currentData()
        user_preset_id = preset_data.get("id") if preset_data else None

        # 스태미나/리소스 추적 필드
        tracking_target = self.hoyolab_game_combo.currentData()
        tracking_checked = self.stamina_tracking_checkbox.isChecked() and tracking_target is not None
        hoyolab_game_id = None
        stamina_tracking_enabled = False
        resource_tracking_enabled = False
        resource_provider = None
        resource_key = None
        resource_label = None

        if tracking_checked and tracking_target == "nikke_outpost_storage":
            resource_tracking_enabled = True
            resource_provider = "nikke_blablalink"
            resource_key = "nikke_outpost_storage"
            resource_label = NIKKE_OUTPOST_LABEL
        elif tracking_checked:
            stamina_tracking_enabled = True
            hoyolab_game_id = tracking_target

        return {
            "name": name,
            "monitoring_path": monitoring_path,
            "launch_path": final_launch_path,
            "server_reset_time_str": server_reset_time,
            "user_cycle_hours": user_cycle_hours,
            "mandatory_times_str": mandatory_times_list if mandatory_times_list else None,
            "is_mandatory_time_enabled": is_mandatory_enabled,
            "preferred_launch_type": preferred_launch_type,
            "user_preset_id": user_preset_id,
            "stamina_tracking_enabled": stamina_tracking_enabled,
            "hoyolab_game_id": hoyolab_game_id,
            "resource_tracking_enabled": resource_tracking_enabled,
            "resource_provider": resource_provider,
            "resource_key": resource_key,
            "resource_label": resource_label,
        }

class GlobalSettingsDialog(QDialog):
    """ Dialog for configuring global application settings. """
    def __init__(self, current_settings: GlobalSettings, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("전역 설정")
        self.current_settings = current_settings
        self.setMinimumWidth(400)

        self.form_layout = QFormLayout(self)  # 변수명 변경

        # === 화면 배율 설정 (OS DPI 무시) ===
        self.scale_combo = QComboBox()
        self.scale_combo.addItem("100%", 100)
        self.scale_combo.addItem("125%", 125)
        self.scale_combo.addItem("150%", 150)
        self.scale_combo.addItem("175%", 175)
        self.scale_combo.addItem("200%", 200)

        scale_info_label = QLabel("※ 변경 시 앱 재시작 필요")
        scale_info_label.setStyleSheet("color: #888888; font-size: 9pt;")

        scale_layout = QHBoxLayout()
        scale_layout.addWidget(self.scale_combo)
        scale_layout.addWidget(scale_info_label)
        scale_layout.addStretch()
        # =====================================

        self.sleep_start_edit = QTimeEdit()
        self.sleep_start_edit.setDisplayFormat("HH:mm")
        self.sleep_end_edit = QTimeEdit()
        self.sleep_end_edit.setDisplayFormat("HH:mm")
        self.sleep_correction_hours_spinbox = QDoubleSpinBox()
        self.sleep_correction_hours_spinbox.setRange(0.0, 5.0)
        self.sleep_correction_hours_spinbox.setSingleStep(0.5)
        self.sleep_correction_hours_spinbox.setSuffix(" 시간 전")
        self.cycle_advance_hours_spinbox = QDoubleSpinBox()
        self.cycle_advance_hours_spinbox.setRange(0.0, 12.0)
        self.cycle_advance_hours_spinbox.setSingleStep(0.25)
        self.cycle_advance_hours_spinbox.setSuffix(" 시간 전")
        self.run_on_startup_checkbox = QCheckBox("Windows 시작 시 자동 실행")
        self.run_as_admin_checkbox = QCheckBox("관리자 권한으로 실행 (UAC 프롬프트 없이)")

        # 테마 선택 (라디오 버튼)
        self.theme_system_rb = QRadioButton("시스템")
        self.theme_light_rb = QRadioButton("라이트")
        self.theme_dark_rb = QRadioButton("다크")
        self._theme_btn_group = QButtonGroup(self)
        self._theme_btn_group.addButton(self.theme_system_rb, 0)
        self._theme_btn_group.addButton(self.theme_light_rb, 1)
        self._theme_btn_group.addButton(self.theme_dark_rb, 2)
        self.theme_system_rb.setChecked(True)
        theme_rb_layout = QHBoxLayout()
        theme_rb_layout.addWidget(self.theme_system_rb)
        theme_rb_layout.addWidget(self.theme_light_rb)
        theme_rb_layout.addWidget(self.theme_dark_rb)
        theme_rb_layout.addStretch()

        # 게임 실행 시 창 숨기기
        self.hide_on_game_checkbox = QCheckBox("게임 실행 감지 시 창을 트레이로 자동 숨기기")
        # --- 알림 설정 체크박스들 ---
        self.notify_on_mandatory_time_checkbox = QCheckBox("고정 접속 시간 알림")
        self.notify_on_cycle_deadline_checkbox = QCheckBox("사용자 주기 만료 임박 알림")
        self.notify_on_sleep_correction_checkbox = QCheckBox("수면 보정(잠들기 전 미리) 알림")
        self.notify_on_daily_reset_checkbox = QCheckBox("일일 과제 마감 임박 알림")
        # 스태미나 알림 설정
        self.stamina_notify_checkbox = QCheckBox("스태미나 가득 찰 알림 (호요버스 게임)")
        self.stamina_threshold_spinbox = QSpinBox()
        self.stamina_threshold_spinbox.setRange(1, 100)
        self.stamina_threshold_spinbox.setSuffix(" 개 전")
        self.stamina_threshold_spinbox.setToolTip("스태미나가 (최대 - 이 값) 이상일 때 알림")

        # 화면 배율 섹션 (맨 위에 배치)
        self.form_layout.addRow("화면 배율:", scale_layout)
        self.form_layout.addRow(QLabel(""))  # 구분선

        self.form_layout.addRow("테마:", theme_rb_layout)
        self.form_layout.addRow(QLabel(""))  # 구분선
        self.form_layout.addRow("수면 시작 시각:", self.sleep_start_edit)
        self.form_layout.addRow("수면 종료 시각:", self.sleep_end_edit)
        self.form_layout.addRow("수면 보정 알림 (수면 시작 기준):", self.sleep_correction_hours_spinbox)
        self.form_layout.addRow("일반 주기 만료 알림 (마감 기준):", self.cycle_advance_hours_spinbox)
        self.form_layout.addRow(self.run_on_startup_checkbox)
        self.form_layout.addRow(self.run_as_admin_checkbox)
        self.form_layout.addRow(self.hide_on_game_checkbox)
        # 알림 설정 섹션
        self.form_layout.addRow(QLabel("알림 설정:"))
        self.form_layout.addRow(self.notify_on_mandatory_time_checkbox)
        self.form_layout.addRow(self.notify_on_cycle_deadline_checkbox)
        self.form_layout.addRow(self.notify_on_sleep_correction_checkbox)
        self.form_layout.addRow(self.notify_on_daily_reset_checkbox)
        # 스태미나 알림 섹션
        self.form_layout.addRow(QLabel("\n스태미나 알림 (호요버스 게임):"))
        self.form_layout.addRow(self.stamina_notify_checkbox)
        self.form_layout.addRow("알림 시점:", self.stamina_threshold_spinbox)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.form_layout.addRow(self.button_box)

        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

        self.populate_settings()

        # 배율 초기값 로드 (ini 파일에서)
        self._load_scale_setting()

    def _load_scale_setting(self):
        """ini 파일에서 배율 설정 로드"""
        try:
            import configparser
            if os.name == 'nt':
                app_data = os.getenv('APPDATA', os.path.expanduser('~'))
            else:
                app_data = os.path.expanduser('~/.config')

            config_path = os.path.join(app_data, 'HomeworkHelper', 'display_settings.ini')

            if os.path.exists(config_path):
                config = configparser.ConfigParser()
                config.read(config_path, encoding='utf-8')
                scale_percent = config.getint('Display', 'scale_percent', fallback=100)
            else:
                scale_percent = 100

            # 콤보박스에서 해당 값 선택
            for i in range(self.scale_combo.count()):
                if self.scale_combo.itemData(i) == scale_percent:
                    self.scale_combo.setCurrentIndex(i)
                    break
        except Exception as e:
            logger.warning(f"배율 설정 로드 실패: {e}")

    def _save_scale_setting(self, scale_percent: int):
        """ini 파일에 배율 설정 저장"""
        try:
            import configparser
            if os.name == 'nt':
                app_data = os.getenv('APPDATA', os.path.expanduser('~'))
            else:
                app_data = os.path.expanduser('~/.config')

            config_dir = os.path.join(app_data, 'HomeworkHelper')
            os.makedirs(config_dir, exist_ok=True)
            config_path = os.path.join(config_dir, 'display_settings.ini')

            config = configparser.ConfigParser()
            config['Display'] = {'scale_percent': str(scale_percent)}

            with open(config_path, 'w', encoding='utf-8') as f:
                config.write(f)

            logger.debug(f"배율 설정 저장: {scale_percent}%")
            return True
        except Exception as e:
            logger.warning(f"배율 설정 저장 실패: {e}")
            return False

    def accept(self):
        """설정 저장 시 배율 변경 확인 및 재시작 안내"""
        new_scale = self.scale_combo.currentData()

        # 기존 배율과 비교
        try:
            import configparser
            if os.name == 'nt':
                app_data = os.getenv('APPDATA', os.path.expanduser('~'))
            else:
                app_data = os.path.expanduser('~/.config')

            config_path = os.path.join(app_data, 'HomeworkHelper', 'display_settings.ini')
            old_scale = 100
            if os.path.exists(config_path):
                config = configparser.ConfigParser()
                config.read(config_path, encoding='utf-8')
                old_scale = config.getint('Display', 'scale_percent', fallback=100)

            # 배율이 변경된 경우
            if new_scale != old_scale:
                self._save_scale_setting(new_scale)
                QMessageBox.information(
                    self,
                    "재시작 필요",
                    f"화면 배율이 {old_scale}% → {new_scale}%로 변경되었습니다.\n\n"
                    "변경 사항을 적용하려면 앱을 재시작해주세요."
                )
        except Exception as e:
            logger.warning(f"배율 변경 확인 실패: {e}")
            self._save_scale_setting(new_scale)

        super().accept()

    def populate_settings(self):
        self.sleep_start_edit.setTime(QTime.fromString(self.current_settings.sleep_start_time_str, "HH:mm"))
        self.sleep_end_edit.setTime(QTime.fromString(self.current_settings.sleep_end_time_str, "HH:mm"))
        self.sleep_correction_hours_spinbox.setValue(self.current_settings.sleep_correction_advance_notify_hours)
        self.cycle_advance_hours_spinbox.setValue(self.current_settings.cycle_deadline_advance_notify_hours)
        self.run_on_startup_checkbox.setChecked(self.current_settings.run_on_startup)
        self.run_as_admin_checkbox.setChecked(self.current_settings.run_as_admin)
        # 테마
        theme = getattr(self.current_settings, 'theme', 'system')
        if theme == 'light':
            self.theme_light_rb.setChecked(True)
        elif theme == 'dark':
            self.theme_dark_rb.setChecked(True)
        else:
            self.theme_system_rb.setChecked(True)
        # 게임 실행 시 창 숨기기
        self.hide_on_game_checkbox.setChecked(getattr(self.current_settings, 'hide_on_game', True))
        # 알림 설정
        self.notify_on_mandatory_time_checkbox.setChecked(self.current_settings.notify_on_mandatory_time)
        self.notify_on_cycle_deadline_checkbox.setChecked(self.current_settings.notify_on_cycle_deadline)
        self.notify_on_sleep_correction_checkbox.setChecked(self.current_settings.notify_on_sleep_correction)
        self.notify_on_daily_reset_checkbox.setChecked(self.current_settings.notify_on_daily_reset)
        # 스태미나 설정
        self.stamina_notify_checkbox.setChecked(self.current_settings.stamina_notify_enabled)
        self.stamina_threshold_spinbox.setValue(self.current_settings.stamina_notify_threshold)

    def get_updated_settings(self) -> GlobalSettings:
        # Start from the latest full settings object so fields managed by other
        # dialogs (sidebar, screenshots, OBS) are preserved when the primary
        # PyQt settings dialog saves only its visible fields.
        updated = GlobalSettings.from_dict(self.current_settings.to_dict())
        updated.sleep_start_time_str = self.sleep_start_edit.time().toString("HH:mm")
        updated.sleep_end_time_str = self.sleep_end_edit.time().toString("HH:mm")
        updated.sleep_correction_advance_notify_hours = self.sleep_correction_hours_spinbox.value()
        updated.cycle_deadline_advance_notify_hours = self.cycle_advance_hours_spinbox.value()
        updated.run_on_startup = self.run_on_startup_checkbox.isChecked()
        updated.always_on_top = self.current_settings.always_on_top  # 메뉴바 체크박스로 관리
        updated.run_as_admin = self.run_as_admin_checkbox.isChecked()
        updated.remote_server_mode_enabled = getattr(self.current_settings, 'remote_server_mode_enabled', False)
        updated.notify_on_mandatory_time = self.notify_on_mandatory_time_checkbox.isChecked()
        updated.notify_on_cycle_deadline = self.notify_on_cycle_deadline_checkbox.isChecked()
        updated.notify_on_sleep_correction = self.notify_on_sleep_correction_checkbox.isChecked()
        updated.notify_on_daily_reset = self.notify_on_daily_reset_checkbox.isChecked()
        updated.stamina_notify_enabled = self.stamina_notify_checkbox.isChecked()
        updated.stamina_notify_threshold = self.stamina_threshold_spinbox.value()
        updated.theme = 'light' if self.theme_light_rb.isChecked() else 'dark' if self.theme_dark_rb.isChecked() else 'system'
        updated.hide_on_game = self.hide_on_game_checkbox.isChecked()
        return updated

class WebShortcutDialog(QDialog):
    """ 웹 바로 가기 버튼 추가 또는 편집을 위한 다이얼로그 """
    def __init__(self, parent: Optional[QWidget] = None, shortcut_data: Optional[Dict[str, Any]] = None):
        super().__init__(parent)

        self.is_edit_mode = shortcut_data is not None
        self.setWindowTitle("웹 바로 가기 편집" if self.is_edit_mode else "새 웹 바로 가기 추가")
        self.setMinimumWidth(350)

        self.form_layout = QFormLayout(self)  # 변수명 변경

        self.name_edit = QLineEdit()
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("예: https://www.google.com")

        # 새로고침 시각 입력 필드 (HH:MM, 선택 사항)
        self.refresh_time_edit = QLineEdit()
        self.refresh_time_edit.setPlaceholderText("HH:MM (예: 09:00), 비워두면 기능 미적용")
        # 선택적으로 QTimeEdit 사용 가능:
        # self.refresh_time_edit = QTimeEdit()
        # self.refresh_time_edit.setDisplayFormat("HH:mm")
        # self.refresh_time_edit.setSpecialValueText("미설정") # QTimeEdit은 None 표현이 어려울 수 있음

        self.form_layout.addRow("버튼 이름 (필수):", self.name_edit)
        self.form_layout.addRow("웹 URL (필수):", self.url_edit)
        self.form_layout.addRow("매일 초기화 시각 (선택):", self.refresh_time_edit) # 레이블 변경

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.form_layout.addRow(self.button_box)

        self.button_box.accepted.connect(self.validate_and_accept)
        self.button_box.rejected.connect(self.reject)

        if self.is_edit_mode and shortcut_data:
            self.name_edit.setText(shortcut_data.get("name", ""))
            self.url_edit.setText(shortcut_data.get("url", ""))
            # refresh_time_str 필드에서 값 로드
            refresh_time_value = shortcut_data.get("refresh_time_str")
            if refresh_time_value:
                self.refresh_time_edit.setText(refresh_time_value)
            # last_reset_timestamp는 이 다이얼로그에서 직접 수정하지 않음

    def _is_valid_hhmm(self, time_str: str) -> bool:
        """ HH:MM 형식인지 검사합니다. """
        if not time_str: # 비어있는 경우 유효 (선택 사항이므로)
            return True
        try:
            datetime.datetime.strptime(time_str, "%H:%M")
            return True
        except ValueError:
            return False

    def validate_and_accept(self):
        name = self.name_edit.text().strip()
        url = self.url_edit.text().strip()
        refresh_time_str = self.refresh_time_edit.text().strip()

        if not name:
            QMessageBox.warning(self, "입력 오류", "버튼 이름을 입력해야 합니다.")
            self.name_edit.setFocus(); return

        if not url:
            QMessageBox.warning(self, "입력 오류", "웹 URL을 입력해야 합니다.")
            self.url_edit.setFocus(); return

        if not (url.startswith("http://") or url.startswith("https://") or "://" in url):
            reply = QMessageBox.warning(self, "URL 형식 경고",
                                        f"입력하신 URL '{url}'이 일반적인 웹 주소 형식이 아닐 수 있습니다.\n"
                                        "그래도 이 URL을 사용하시겠습니까?",
                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                        QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No:
                self.url_edit.setFocus(); return

        if refresh_time_str and not self._is_valid_hhmm(refresh_time_str):
            QMessageBox.warning(self, "입력 오류", "새로고침 시각 형식이 잘못되었습니다 (HH:MM 형식 또는 빈 값).")
            self.refresh_time_edit.setFocus(); return

        self.accept()

    def get_data(self) -> Optional[Dict[str, Any]]:
        if self.result() == QDialog.DialogCode.Accepted:
            refresh_time_str = self.refresh_time_edit.text().strip()
            return {
                "name": self.name_edit.text().strip(),
                "url": self.url_edit.text().strip(),
                # 비어있으면 None으로 저장, 아니면 HH:MM 문자열 저장
                "refresh_time_str": refresh_time_str if refresh_time_str else None,
                # last_reset_timestamp는 여기서 설정하지 않음 (기존 값 유지 또는 로직에서 초기화)
            }
        return None


class HoYoLabAdvancedCredentialsDialog(QDialog):
    """HoYoLab 쿠키를 수동 확인/수정하는 고급 다이얼로그."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("HoYoLab 고급 인증 정보")
        self.setMinimumWidth(520)
        self._existing_credentials: dict[str, Any] = {}

        layout = QVBoxLayout(self)
        info = QLabel("자동 추출이 실패했거나 저장된 HoYoLab 쿠키를 직접 수정해야 할 때만 사용하세요.")
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QFormLayout()
        self.ltuid_field = QLineEdit()
        self.ltuid_field.setPlaceholderText("숫자로 된 사용자 ID")
        self.ltoken_field = QLineEdit()
        self.ltoken_field.setPlaceholderText("ltoken_v2 쿠키 값")
        self.ltoken_field.setEchoMode(QLineEdit.EchoMode.Password)
        self.ltmid_field = QLineEdit()
        self.ltmid_field.setPlaceholderText("ltmid_v2 쿠키 값 (없으면 비워도 됨)")
        self.ltmid_field.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("LTUID:", self.ltuid_field)
        form.addRow("LTOKEN_V2:", self.ltoken_field)
        form.addRow("LTMID_V2:", self.ltmid_field)
        layout.addLayout(form)

        self.show_tokens_checkbox = QCheckBox("토큰 값 표시")
        self.show_tokens_checkbox.toggled.connect(self._toggle_token_visibility)
        layout.addWidget(self.show_tokens_checkbox)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self._save_credentials)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self._load_existing_credentials()

    def _toggle_token_visibility(self, checked: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        self.ltoken_field.setEchoMode(mode)
        self.ltmid_field.setEchoMode(mode)

    def _load_existing_credentials(self) -> None:
        try:
            from src.utils.hoyolab_config import HoYoLabConfig

            self._existing_credentials = HoYoLabConfig().load_credentials() or {}
            if self._existing_credentials:
                self.ltuid_field.setText(str(self._existing_credentials.get("ltuid", "")))
                self.ltoken_field.setText(str(self._existing_credentials.get("ltoken_v2", "")))
                self.ltmid_field.setText(str(self._existing_credentials.get("ltmid_v2", "")))
                self.status_label.setText("저장된 HoYoLab 쿠키를 불러왔습니다.")
                self.status_label.setStyleSheet("color: #44cc44;")
            else:
                self.status_label.setText("저장된 HoYoLab 쿠키가 없습니다.")
                self.status_label.setStyleSheet("color: #ffcc00;")
        except Exception as exc:
            self.status_label.setText(f"⚠️ HoYoLab 쿠키 로드 실패: {exc}")
            self.status_label.setStyleSheet("color: #ffcc00;")

    def _save_credentials(self) -> None:
        ltuid_text = self.ltuid_field.text().strip()
        ltoken = self.ltoken_field.text().strip()
        ltmid = self.ltmid_field.text().strip()
        if not ltuid_text or not ltoken:
            self.status_label.setText("❌ LTUID와 LTOKEN_V2는 필수입니다.")
            self.status_label.setStyleSheet("color: #ff6666;")
            return
        try:
            ltuid = int(ltuid_text)
        except ValueError:
            self.status_label.setText("❌ LTUID는 숫자여야 합니다.")
            self.status_label.setStyleSheet("color: #ff6666;")
            return

        try:
            from src.utils.hoyolab_config import HoYoLabConfig
            from src.services.hoyolab import reset_hoyolab_service

            config = HoYoLabConfig()
            if config.save_credentials(
                ltuid,
                ltoken,
                ltmid,
                starrail_uid=self._existing_credentials.get("starrail_uid"),
                zzz_uid=self._existing_credentials.get("zzz_uid"),
            ):
                reset_hoyolab_service()
                self.accept()
            else:
                self.status_label.setText("❌ HoYoLab 쿠키 저장에 실패했습니다.")
                self.status_label.setStyleSheet("color: #ff6666;")
        except Exception as exc:
            self.status_label.setText(f"❌ HoYoLab 쿠키 저장 실패: {exc}")
            self.status_label.setStyleSheet("color: #ff6666;")


class NikkeAdvancedSessionDialog(QDialog):
    """BlablaLink 쿠키와 ShiftyPad 대표 계정 cache를 수동 확인/수정합니다."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("NIKKE / BlablaLink 고급 인증 정보")
        self.setMinimumWidth(620)

        layout = QVBoxLayout(self)
        info = QLabel(
            "자동 추출이 실패했거나 저장된 BlablaLink 쿠키를 직접 수정해야 할 때만 사용하세요. "
            "쿠키는 name=value 형식으로 한 줄씩 입력하거나, 세미콜론으로 구분된 Cookie header를 붙여넣을 수 있습니다."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QFormLayout()
        self.cookie_text = QTextEdit()
        self.cookie_text.setPlaceholderText("session_id=...\napi_cookie=...")
        self.cookie_text.setMinimumHeight(120)
        self.open_id_field = QLineEdit()
        self.open_id_field.setPlaceholderText("선택: ShiftyPad intl_open_id cache")
        self.area_id_field = QLineEdit()
        self.area_id_field.setPlaceholderText("선택: ShiftyPad 서버 area_id cache")
        form.addRow("Cookies:", self.cookie_text)
        form.addRow("intl_open_id:", self.open_id_field)
        form.addRow("nikke_area_id:", self.area_id_field)
        layout.addLayout(form)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self._save_session)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self._load_existing_session()

    def _load_existing_session(self) -> None:
        try:
            from src.utils.nikke_config import NikkeConfig

            session = NikkeConfig().load_session() or {}
            cookies = session.get("cookies") or {}
            self.cookie_text.setPlainText("\n".join(f"{key}={value}" for key, value in sorted(cookies.items())))
            if session.get("intl_open_id"):
                self.open_id_field.setText(str(session.get("intl_open_id")))
            if session.get("nikke_area_id") is not None:
                self.area_id_field.setText(str(session.get("nikke_area_id")))
            if cookies:
                self.status_label.setText("저장된 BlablaLink 쿠키를 불러왔습니다.")
                self.status_label.setStyleSheet("color: #44cc44;")
            else:
                self.status_label.setText("저장된 BlablaLink 쿠키가 없습니다.")
                self.status_label.setStyleSheet("color: #ffcc00;")
        except Exception as exc:
            self.status_label.setText(f"⚠️ BlablaLink 쿠키 로드 실패: {exc}")
            self.status_label.setStyleSheet("color: #ffcc00;")

    @staticmethod
    def _parse_cookie_text(raw_text: str) -> dict[str, str]:
        cookies: dict[str, str] = {}
        for chunk in raw_text.replace(";", "\n").splitlines():
            line = chunk.strip()
            if not line or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if key:
                cookies[key] = value
        return cookies

    def _save_session(self) -> None:
        cookies = self._parse_cookie_text(self.cookie_text.toPlainText())
        if not cookies:
            self.status_label.setText("❌ 저장할 BlablaLink 쿠키가 없습니다.")
            self.status_label.setStyleSheet("color: #ff6666;")
            return
        area_id = self.area_id_field.text().strip() or None
        open_id = self.open_id_field.text().strip() or None
        try:
            from src.utils.nikke_config import NikkeConfig
            from src.services.nikke import reset_nikke_service

            if NikkeConfig().save_session(cookies, intl_open_id=open_id, nikke_area_id=area_id):
                reset_nikke_service()
                self.accept()
            else:
                self.status_label.setText("❌ BlablaLink 쿠키 저장에 실패했습니다.")
                self.status_label.setStyleSheet("color: #ff6666;")
        except Exception as exc:
            self.status_label.setText(f"❌ BlablaLink 쿠키 저장 실패: {exc}")
            self.status_label.setStyleSheet("color: #ff6666;")


class HoYoLabSettingsDialog(QDialog):
    """자원 추적용 HoYoLab/BlablaLink 인증 정보 설정 다이얼로그."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("자원 추적 설정")
        self.setMinimumWidth(500)

        layout = QVBoxLayout(self)

        info_label = QLabel(
            "게임 스태미나/리소스 자동 추적을 위해 HoYoLab 또는 BlablaLink 로그인 쿠키가 필요합니다.\n"
            "일반적으로 브라우저 자동 추출을 사용하고, 직접 수정이 필요할 때만 고급 설정을 여세요."
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        self._build_hoyolab_section(layout)
        self._build_nikke_section(layout)

        status_group = QGroupBox("유효성 검사")
        status_layout = QVBoxLayout(status_group)
        self.check_cookies_btn = QPushButton("쿠키 유효성 검사")
        self.check_cookies_btn.setToolTip("저장된 HoYoLab/BlablaLink 쿠키로 실제 읽기 전용 조회가 가능한지 확인합니다.")
        self.cookie_check_status_label = QLabel("저장된 쿠키를 검사하려면 버튼을 누르세요.")
        self.cookie_check_status_label.setWordWrap(True)
        status_layout.addWidget(self.check_cookies_btn)
        status_layout.addWidget(self.cookie_check_status_label)
        layout.addWidget(status_group)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        self.extract_chrome_btn.clicked.connect(lambda: self._extract_cookies("chrome"))
        self.extract_edge_btn.clicked.connect(lambda: self._extract_cookies("edge"))
        self.extract_firefox_btn.clicked.connect(lambda: self._extract_cookies("firefox"))
        self.extract_nikke_chrome_btn.clicked.connect(lambda: self._extract_nikke_cookies("chrome"))
        self.extract_nikke_edge_btn.clicked.connect(lambda: self._extract_nikke_cookies("edge"))
        self.extract_nikke_firefox_btn.clicked.connect(lambda: self._extract_nikke_cookies("firefox"))
        self.open_hoyolab_btn.clicked.connect(self._open_hoyolab)
        self.open_nikke_btn.clicked.connect(self._open_nikke)
        self.hoyolab_advanced_btn.clicked.connect(self._open_hoyolab_advanced)
        self.nikke_advanced_btn.clicked.connect(self._open_nikke_advanced)
        self.clear_btn.clicked.connect(self._clear_credentials)
        self.clear_nikke_btn.clicked.connect(self._clear_nikke_credentials)
        self.check_cookies_btn.clicked.connect(self._check_cookie_availability)

        self._update_status()
        self._update_nikke_status()

    def _build_hoyolab_section(self, root: QVBoxLayout) -> None:
        auto_group = QGroupBox("HoYoLab")
        auto_layout = QVBoxLayout(auto_group)

        info = QLabel("스타레일/젠레스 존 제로 스태미나 조회를 위한 HoYoLab 쿠키를 관리합니다.")
        info.setWordWrap(True)
        auto_layout.addWidget(info)

        extract_btn_layout = QHBoxLayout()
        self.extract_chrome_btn = QPushButton("크롬에서 추출")
        self.extract_edge_btn = QPushButton("엣지에서 추출")
        self.extract_firefox_btn = QPushButton("파이어폭스에서 추출")
        extract_btn_layout.addWidget(self.extract_chrome_btn)
        extract_btn_layout.addWidget(self.extract_edge_btn)
        extract_btn_layout.addWidget(self.extract_firefox_btn)
        auto_layout.addLayout(extract_btn_layout)

        button_layout = QHBoxLayout()
        self.open_hoyolab_btn = QPushButton("HoYoLab 로그인 열기")
        self.hoyolab_advanced_btn = QPushButton("고급")
        self.clear_btn = QPushButton("HoYoLab 인증 삭제")
        self.clear_btn.setStyleSheet("color: #ff6666;")
        button_layout.addWidget(self.open_hoyolab_btn)
        button_layout.addWidget(self.hoyolab_advanced_btn)
        button_layout.addWidget(self.clear_btn)
        auto_layout.addLayout(button_layout)

        self.extract_status_label = QLabel("")
        self.extract_status_label.setWordWrap(True)
        auto_layout.addWidget(self.extract_status_label)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        auto_layout.addWidget(self.status_label)

        root.addWidget(auto_group)

    def _build_nikke_section(self, root: QVBoxLayout) -> None:
        nikke_group = QGroupBox("NIKKE / BlablaLink")
        nikke_layout = QVBoxLayout(nikke_group)

        nikke_info = QLabel("ShiftyPad 전초기지 방어 보상 조회를 위한 BlablaLink 로그인 세션 쿠키를 관리합니다.")
        nikke_info.setWordWrap(True)
        nikke_layout.addWidget(nikke_info)

        nikke_extract_layout = QHBoxLayout()
        self.extract_nikke_chrome_btn = QPushButton("크롬에서 추출")
        self.extract_nikke_edge_btn = QPushButton("엣지에서 추출")
        self.extract_nikke_firefox_btn = QPushButton("파이어폭스에서 추출")
        nikke_extract_layout.addWidget(self.extract_nikke_chrome_btn)
        nikke_extract_layout.addWidget(self.extract_nikke_edge_btn)
        nikke_extract_layout.addWidget(self.extract_nikke_firefox_btn)
        nikke_layout.addLayout(nikke_extract_layout)

        nikke_button_layout = QHBoxLayout()
        self.open_nikke_btn = QPushButton("BlablaLink 열기")
        self.nikke_advanced_btn = QPushButton("고급")
        self.clear_nikke_btn = QPushButton("NIKKE 인증 삭제")
        self.clear_nikke_btn.setStyleSheet("color: #ff6666;")
        nikke_button_layout.addWidget(self.open_nikke_btn)
        nikke_button_layout.addWidget(self.nikke_advanced_btn)
        nikke_button_layout.addWidget(self.clear_nikke_btn)
        nikke_layout.addLayout(nikke_button_layout)

        self.nikke_status_label = QLabel("")
        self.nikke_status_label.setWordWrap(True)
        nikke_layout.addWidget(self.nikke_status_label)

        root.addWidget(nikke_group)

    def _update_status(self):
        """현재 HoYoLab 인증 상태 업데이트"""
        try:
            from src.utils.hoyolab_config import HoYoLabConfig
            config = HoYoLabConfig()
            if config.is_configured():
                self.status_label.setText("✅ HoYoLab 인증 정보가 설정되어 있습니다.")
                self.status_label.setStyleSheet("color: #44cc44;")
            else:
                self.status_label.setText("❌ HoYoLab 인증 정보가 없습니다.")
                self.status_label.setStyleSheet("color: #ff6666;")
        except Exception as e:
            self.status_label.setText(f"⚠️ HoYoLab 상태 확인 실패: {e}")
            self.status_label.setStyleSheet("color: #ffcc00;")

    def _extract_cookies(self, browser: str):
        """브라우저에서 HoYoLab 쿠키를 추출하고 즉시 저장합니다."""
        try:
            from src.utils.browser_cookie_extractor import BrowserCookieExtractor
            from src.utils.hoyolab_config import HoYoLabConfig
            from src.services.hoyolab import reset_hoyolab_service

            extractor = BrowserCookieExtractor()
            if not extractor.is_available(browser):
                self.extract_status_label.setText(
                    f"❌ {browser} 쿠키 추출을 사용할 수 없습니다. Firefox 프로필 또는 Chrome/Edge 복호화 의존성을 확인하세요."
                )
                self.extract_status_label.setStyleSheet("color: #ff6666;")
                return

            self.extract_status_label.setText(f"{browser}에서 HoYoLab 쿠키 추출 중...")
            self.extract_status_label.repaint()

            cookies = extractor.extract_from_browser(browser, provider="hoyolab")
            if cookies:
                config = HoYoLabConfig()
                ltmid = cookies.get("ltmid_v2", "")
                if config.save_credentials(int(cookies.get("ltuid")), cookies.get("ltoken_v2", ""), ltmid):
                    reset_hoyolab_service()
                    self.extract_status_label.setText(f"✅ {browser}에서 HoYoLab 쿠키를 추출해 저장했습니다.")
                    self.extract_status_label.setStyleSheet("color: #44cc44;")
                    self._update_status()
                else:
                    self.extract_status_label.setText("❌ HoYoLab 쿠키 저장 실패")
                    self.extract_status_label.setStyleSheet("color: #ff6666;")
            else:
                self.extract_status_label.setText(
                    f"❌ {browser}에서 HoYoLab 쿠키를 찾을 수 없습니다. HoYoLab에 로그인한 후 다시 시도하세요."
                )
                self.extract_status_label.setStyleSheet("color: #ff6666;")
        except Exception as e:
            self.extract_status_label.setText(f"❌ HoYoLab 추출 실패: {e}")
            self.extract_status_label.setStyleSheet("color: #ff6666;")

    def _update_nikke_status(self):
        """현재 NIKKE/BlablaLink 인증 상태 업데이트"""
        try:
            from src.utils.nikke_config import NikkeConfig

            config = NikkeConfig()
            if config.is_configured():
                self.nikke_status_label.setText("✅ NIKKE/BlablaLink 인증 정보가 설정되어 있습니다.")
                self.nikke_status_label.setStyleSheet("color: #44cc44;")
            else:
                self.nikke_status_label.setText("❌ NIKKE/BlablaLink 인증 정보가 없습니다.")
                self.nikke_status_label.setStyleSheet("color: #ff6666;")
        except Exception as e:
            self.nikke_status_label.setText(f"⚠️ NIKKE 상태 확인 실패: {e}")
            self.nikke_status_label.setStyleSheet("color: #ffcc00;")

    def _extract_nikke_cookies(self, browser: str):
        """브라우저에서 BlablaLink 쿠키 자동 추출"""
        try:
            from src.utils.browser_cookie_extractor import BrowserCookieExtractor
            from src.utils.nikke_config import NikkeConfig
            from src.services.nikke import NikkeService, reset_nikke_service

            extractor = BrowserCookieExtractor()
            if not extractor.is_available(browser):
                self.nikke_status_label.setText(
                    f"❌ {browser} 쿠키 추출을 사용할 수 없습니다. Firefox 프로필 또는 Chrome/Edge 복호화 의존성을 확인하세요."
                )
                self.nikke_status_label.setStyleSheet("color: #ff6666;")
                return

            self.nikke_status_label.setText(f"{browser}에서 BlablaLink 쿠키 추출 중...")
            self.nikke_status_label.repaint()

            extracted = extractor.extract_from_browser(browser, provider="nikke_blablalink")
            cookies = (extracted or {}).get("cookies") if isinstance(extracted, dict) else None
            if cookies:
                config = NikkeConfig()
                if config.save_session(cookies):
                    reset_nikke_service()
                    self.nikke_status_label.setText("BlablaLink 쿠키 저장 완료. ShiftyPad 대표 계정/서버 정보 확인 중...")
                    self.nikke_status_label.repaint()

                    role = NikkeService(config=config).get_role_info(refresh=True)
                    reset_nikke_service()
                    if role:
                        self.nikke_status_label.setText(
                            f"✅ {browser}에서 BlablaLink 쿠키와 ShiftyPad 대표 계정 정보를 확인했습니다. "
                            f"서버={role.nikke_area_id}, open_id={self._mask_identifier(role.intl_open_id)}"
                        )
                        self.nikke_status_label.setStyleSheet("color: #44cc44;")
                    else:
                        self.nikke_status_label.setText(
                            f"⚠️ {browser}에서 BlablaLink 쿠키는 저장했지만 ShiftyPad 대표 계정/서버 정보를 찾지 못했습니다.\n"
                            "BlablaLink에서 ShiftyPad를 열어 대표 계정이 보이는지 확인한 뒤 다시 추출하세요."
                        )
                        self.nikke_status_label.setStyleSheet("color: #ffcc00;")
                else:
                    self.nikke_status_label.setText("❌ BlablaLink 쿠키 저장 실패")
                    self.nikke_status_label.setStyleSheet("color: #ff6666;")
            else:
                self.nikke_status_label.setText(
                    f"❌ {browser}에서 BlablaLink 쿠키를 찾을 수 없습니다. BlablaLink/ShiftyPad에 로그인한 후 다시 시도하세요."
                )
                self.nikke_status_label.setStyleSheet("color: #ff6666;")
        except Exception as e:
            self.nikke_status_label.setText(f"❌ NIKKE 추출 실패: {e}")
            self.nikke_status_label.setStyleSheet("color: #ff6666;")

    @staticmethod
    def _mask_identifier(value: str) -> str:
        text = str(value or "")
        if len(text) <= 4:
            return "••••"
        return f"{text[:2]}•••{text[-2:]}"

    def _open_hoyolab_advanced(self) -> None:
        dialog = HoYoLabAdvancedCredentialsDialog(self)
        if dialog.exec():
            self._update_status()
            self.extract_status_label.setText("✅ HoYoLab 고급 인증 정보가 저장되었습니다.")
            self.extract_status_label.setStyleSheet("color: #44cc44;")

    def _open_nikke_advanced(self) -> None:
        dialog = NikkeAdvancedSessionDialog(self)
        if dialog.exec():
            self._update_nikke_status()
            self.nikke_status_label.setText("✅ NIKKE/BlablaLink 고급 인증 정보가 저장되었습니다.")
            self.nikke_status_label.setStyleSheet("color: #44cc44;")

    def _open_nikke(self):
        """BlablaLink 로그인 웹사이트 열기"""
        try:
            from src.utils.browser_cookie_extractor import BrowserCookieExtractor

            BrowserCookieExtractor().open_nikke_login()
            self.nikke_status_label.setText("브라우저에서 BlablaLink에 로그인한 후 쿠키를 추출하세요.")
        except Exception:
            import webbrowser

            webbrowser.open("https://www.blablalink.com/login")

    def _clear_nikke_credentials(self):
        """저장된 NIKKE/BlablaLink 인증 정보 삭제"""
        reply = QMessageBox.question(
            self, "NIKKE 인증 정보 삭제",
            "저장된 NIKKE/BlablaLink 인증 정보를 삭제하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                from src.utils.nikke_config import NikkeConfig
                from src.services.nikke import reset_nikke_service

                NikkeConfig().clear_session()
                reset_nikke_service()
                self._update_nikke_status()
                self.cookie_check_status_label.setText("NIKKE/BlablaLink 인증 정보가 삭제되었습니다.")
            except Exception as e:
                QMessageBox.warning(self, "오류", f"삭제 실패: {e}")

    def _open_hoyolab(self):
        """HoYoLab 웹사이트 열기"""
        try:
            from src.utils.browser_cookie_extractor import BrowserCookieExtractor
            extractor = BrowserCookieExtractor()
            extractor.open_hoyolab_login()
            self.extract_status_label.setText("브라우저에서 HoYoLab에 로그인한 후 쿠키를 추출하세요.")
        except Exception:
            import webbrowser
            webbrowser.open("https://www.hoyolab.com/home")

    def _clear_credentials(self):
        """저장된 HoYoLab 인증 정보 삭제"""
        reply = QMessageBox.question(
            self, "HoYoLab 인증 정보 삭제",
            "저장된 HoYoLab 인증 정보를 삭제하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                from src.utils.hoyolab_config import HoYoLabConfig
                from src.services.hoyolab import reset_hoyolab_service

                HoYoLabConfig().clear_credentials()
                reset_hoyolab_service()
                self._update_status()
                self.cookie_check_status_label.setText("HoYoLab 인증 정보가 삭제되었습니다.")
            except Exception as e:
                QMessageBox.warning(self, "오류", f"삭제 실패: {e}")

    def _check_cookie_availability(self) -> None:
        self.check_cookies_btn.setEnabled(False)
        self.cookie_check_status_label.setText("HoYoLab/BlablaLink 쿠키 유효성 검사 중...")
        self.cookie_check_status_label.setStyleSheet("color: #ffcc00;")
        QApplication.processEvents()
        try:
            lines = [self._check_hoyolab_availability(), self._check_nikke_availability()]
            self.cookie_check_status_label.setText("\n".join(lines))
            if all(line.startswith("✅") for line in lines):
                self.cookie_check_status_label.setStyleSheet("color: #44cc44;")
            elif any(line.startswith("✅") for line in lines):
                self.cookie_check_status_label.setStyleSheet("color: #ffcc00;")
            else:
                self.cookie_check_status_label.setStyleSheet("color: #ff6666;")
        finally:
            self.check_cookies_btn.setEnabled(True)

    def _check_hoyolab_availability(self) -> str:
        try:
            from src.services.hoyolab import HoYoLabService
            from src.utils.hoyolab_config import HoYoLabConfig

            if not HoYoLabConfig().is_configured():
                return "❌ HoYoLab: 저장된 쿠키가 없습니다."
            service = HoYoLabService()
            try:
                if not service.is_available():
                    return "❌ HoYoLab: genshin.py 라이브러리를 사용할 수 없습니다."
                starrail = service.get_stamina("honkai_starrail")
                zzz = service.get_stamina("zenless_zone_zero")
                results = []
                if starrail:
                    results.append(f"스타레일 {starrail.current}/{starrail.max}")
                if zzz:
                    results.append(f"젠레스 존 제로 {zzz.current}/{zzz.max}")
                if results:
                    return "✅ HoYoLab: " + ", ".join(results)
                return "⚠️ HoYoLab: 쿠키는 저장되어 있지만 스태미나 조회에 실패했습니다."
            finally:
                service.close()
        except Exception as exc:
            return f"❌ HoYoLab: 검사 실패 - {exc}"

    def _check_nikke_availability(self) -> str:
        try:
            from src.services.nikke import NikkeService, NIKKE_OUTPOST_LABEL
            from src.utils.nikke_config import NikkeConfig

            config = NikkeConfig()
            if not config.is_configured():
                return "❌ BlablaLink: 저장된 쿠키가 없습니다."
            service = NikkeService(config=config)
            ok, message = service.check_login()
            if not ok:
                return f"❌ BlablaLink: 로그인 세션 확인 실패 ({message})"
            role = service.get_role_info(refresh=True)
            if not role:
                return "⚠️ BlablaLink: 로그인은 유효하지만 ShiftyPad 대표 계정/서버 정보를 찾지 못했습니다."
            snapshot = service.get_outpost_storage()
            if snapshot.status == "ok" and snapshot.percent is not None:
                return f"✅ BlablaLink: {NIKKE_OUTPOST_LABEL} {snapshot.percent:.1f}% (서버={role.nikke_area_id})"
            return f"⚠️ BlablaLink: 대표 계정 확인됨, 리소스 조회 실패 ({snapshot.status})"
        except Exception as exc:
            return f"❌ BlablaLink: 검사 실패 - {exc}"
