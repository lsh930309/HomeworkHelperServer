"""PySide6 Widgets for Beholder incidents and database backup recovery."""

from __future__ import annotations

import datetime
from typing import Any
from PySide6.QtCore import QThread, Signal

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QTextEdit, QVBoxLayout,
)

from src.api.client import BackgroundApiTransport


class _RestoreRequest(QThread):
    completed = Signal(object, object)

    def __init__(self, transport, slot, parent):
        super().__init__(parent)
        self.transport, self.slot = transport, slot

    def run(self):
        try:
            result = self.transport.post_json(
                "/api/beholder/backups/restore", {"slot": self.slot}, timeout=20.0
            ).payload
            self.completed.emit(result, None)
        except Exception as exc:
            self.completed.emit(None, exc)


class BeholderBackupRestoreDialog(QDialog):
    """Use only recovery APIs, including before the normal API client exists."""

    def __init__(
        self, base_url: str, parent=None, *, database_faulted: bool = False,
    ):
        super().__init__(parent)
        self._transport = BackgroundApiTransport(base_url)
        self._request_worker = None
        self._restore_allowed = True
        self.restored = False
        self.restart_required = False
        self.setWindowTitle("Beholder 백업 복구")
        self.setMinimumWidth(560)
        lead = QLabel(
            "DB 보호 상태로 일반 기능을 시작하지 않았습니다. 백업으로 복구하거나 앱을 종료할 수 있습니다."
            if database_faulted else
            "복구할 백업을 선택하세요. 기존 DB는 교체 전에 별도로 보존됩니다."
        )
        lead.setWordWrap(True)
        self._backups = QComboBox(self)
        self._summary = QLabel(self)
        self._summary.setWordWrap(True)
        self._restart_notice = QLabel(self)
        self._restart_notice.setWordWrap(True)
        self._refresh_button = QPushButton("백업 다시 조회", self)
        self._restore_button = QPushButton("선택한 백업으로 복구", self)
        close_button = QPushButton("앱 종료" if database_faulted else "취소", self)
        self._refresh_button.clicked.connect(self._load_backups)
        self._restore_button.clicked.connect(self._restore_selected)
        close_button.clicked.connect(self.reject)
        self._backups.currentIndexChanged.connect(self._show_backup_summary)
        buttons = QHBoxLayout()
        buttons.addWidget(self._refresh_button)
        buttons.addWidget(self._restore_button)
        buttons.addWidget(close_button)
        layout = QVBoxLayout(self)
        layout.addWidget(lead)
        layout.addWidget(self._backups)
        layout.addWidget(self._summary)
        layout.addWidget(self._restart_notice)
        layout.addLayout(buttons)
        self._load_backups()

    def activate_and_show(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _show_backup_summary(self) -> None:
        backup = self._backups.currentData()
        if isinstance(backup, dict):
            self._summary.setText(str(backup.get("user_summary") or "선택한 백업을 복구 전에 확인합니다."))

    def _load_backups(self) -> None:
        self._backups.clear()
        self._restore_button.setEnabled(False)
        try:
            payload = self._transport.get_json("/api/beholder/backups", timeout=5.0).payload
            for item in payload.get("backups", []):
                timestamp = datetime.datetime.fromtimestamp(item.get("modified_at", 0))
                label = f"백업 {item['slot']} · {timestamp:%Y-%m-%d %H:%M:%S} · {item.get('size', 0)} bytes"
                self._backups.addItem(label, item)
            self._restore_button.setEnabled(self._restore_allowed and self._backups.count() > 0)
            if self._backups.count() == 0:
                self._summary.setText("사용 가능한 백업이 없습니다. 백업을 준비한 뒤 다시 조회하거나 종료하세요.")
        except Exception as exc:
            self._summary.setText(f"백업 목록을 조회하지 못했습니다. 다시 조회할 수 있습니다.\n{exc}")

    def _restore_selected(self) -> None:
        if not self._restore_allowed:
            return
        backup = self._backups.currentData()
        if not isinstance(backup, dict):
            return
        slot = int(backup["slot"])
        self._restore_button.setEnabled(False)
        self._refresh_button.setEnabled(False)
        try:
            preview = self._transport.post_json(
                "/api/beholder/backups/restore-preview", {"slot": slot}, timeout=10.0
            ).payload
            summary = preview.get("impact", {}).get("summary") or "현재 DB를 선택한 백업으로 교체합니다."
            confirmed = QMessageBox.question(
                self, "백업 복구 확인", f"{summary}\n계속할까요?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if confirmed != QMessageBox.StandardButton.Yes:
                return
            self.restart_required = True
            self._restart_notice.setText("복구 준비 후에는 앱 재시작이 필요합니다.")
            self._request_worker = _RestoreRequest(self._transport, slot, self)
            self._request_worker.completed.connect(self._restore_completed)
            self._request_worker.finished.connect(self._request_finished)
            self._request_worker.start()
        except Exception as exc:
            if not self._restore_allowed:
                self._restart_notice.setText("데이터 기록 작업의 중단을 확인하지 못해 복구를 진행하지 않았습니다. 앱을 재시작하세요.")
                self._summary.setText(f"복구를 진행할 수 없습니다.\n{exc}")
            else:
                self._summary.setText(f"복구에 실패했습니다. 데이터 보호를 유지하며 다시 시도할 수 있습니다.\n{exc}")
        finally:
            if self._request_worker is None:
                self._enable_retry()

    def prepare_database_restore(self) -> bool:
        # Startup recovery has no normal runtime consumers.
        return True

    def reject(self) -> None:
        if self._request_worker is None:
            super().reject()

    def _restore_completed(self, result, error) -> None:
        if error is None and isinstance(result, dict) and result.get("ok") is True:
            self.restored = True
        else:
            self._summary.setText(f"복구에 실패했습니다. 데이터 보호를 유지하며 다시 시도할 수 있습니다.\n{error or '복구 완료를 확인하지 못했습니다.'}")

    def _request_finished(self) -> None:
        worker, self._request_worker = self._request_worker, None
        worker.deleteLater()
        if self.restored:
            self.accept()
        else:
            self._enable_retry()

    def _enable_retry(self) -> None:
        self._refresh_button.setEnabled(True)
        self._restore_button.setEnabled(self._restore_allowed and self._backups.count() > 0)


class BeholderIncidentDialog(QDialog):
    def __init__(self, incident: dict[str, Any], parent=None):
        super().__init__(parent)
        self.incident = incident
        self.action: str | None = None
        self.setWindowTitle("Beholder 데이터 보호 안내")
        self.setMinimumWidth(560)

        title = QLabel(incident.get("user_title") or "데이터 변경 확인이 필요합니다")
        title.setStyleSheet("font-size: 17px; font-weight: 800; color: #f3d27a;")

        lead = QLabel(incident.get("user_summary") or "Beholder가 저장 전에 변경 내용을 확인했습니다.")
        lead.setWordWrap(True)

        impact = QLabel(incident.get("user_impact") or "현재 데이터는 변경되지 않았습니다.")
        impact.setWordWrap(True)
        recommendation = QLabel(
            f"권장 조치: {incident.get('safe_recommendation') or '차단을 유지하세요.'}"
        )
        recommendation.setWordWrap(True)

        technical_toggle = QPushButton("기술 정보 보기")
        technical_toggle.setCheckable(True)
        technical = QTextEdit()
        technical.setReadOnly(True)
        technical.setMinimumHeight(220)
        technical.setVisible(False)
        factors = incident.get("risk_factors") or []
        factor_text = "\n".join(f"- {item}" for item in factors) or "- 없음"
        technical.setPlainText(
            f"사건 ID: {incident.get('id') or '-'}\n"
            f"심각도: {incident.get('severity', 'warning')} / 위험도: {incident.get('risk_score', 0)}/100\n"
            f"내부 동작: {incident.get('operation_kind') or '-'} / {incident.get('actor') or '-'}\n"
            f"내부 대상: {incident.get('target_summary') or '-'}\n\n"
            f"현재 DB 상태\n{incident.get('current_state_summary') or '-'}\n\n"
            f"저장하려던 변경\n{incident.get('proposed_change_summary') or '-'}\n\n"
            f"위험 신호\n{factor_text}"
        )

        def toggle_technical(checked: bool) -> None:
            technical.setVisible(checked)
            technical_toggle.setText("기술 정보 접기" if checked else "기술 정보 보기")
            self.adjustSize()

        technical_toggle.toggled.connect(toggle_technical)

        buttons = QDialogButtonBox()
        actions = incident.get("available_actions") or []
        if not actions:
            actions = [
                {"id": "deny", "label": "차단 유지"},
                {"id": "quarantine", "label": "격리"},
                {"id": "allow_once", "label": "이번 한 번 허용"},
            ]
        action_explanations: list[str] = []
        for action in actions:
            action_id = action.get("id")
            if not action_id:
                continue
            label = action.get("label") or action_id
            if action.get("recommended"):
                label = f"★ {label}"
            outcome = action.get("outcome") or action.get("description")
            if outcome:
                action_explanations.append(f"{label}: {outcome}")
            button = QPushButton(label)
            button.setToolTip(action.get("description") or "")
            role = QDialogButtonBox.ButtonRole.AcceptRole if action.get("recommended") else QDialogButtonBox.ButtonRole.ActionRole
            if action.get("danger"):
                role = QDialogButtonBox.ButtonRole.DestructiveRole
            if action_id == "deny":
                role = QDialogButtonBox.ButtonRole.RejectRole
            buttons.addButton(button, role)
            button.clicked.connect(lambda _checked=False, selected=action_id: self._finish(selected))
        restore_button = QPushButton("백업으로 복구")
        buttons.addButton(restore_button, QDialogButtonBox.ButtonRole.ActionRole)
        restore_button.clicked.connect(lambda: self._finish("restore_backup"))
        choices = QLabel("\n".join(action_explanations))
        choices.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(lead)
        layout.addWidget(impact)
        layout.addWidget(recommendation)
        layout.addWidget(choices)
        layout.addWidget(technical_toggle)
        layout.addWidget(technical)
        layout.addWidget(buttons)

    def _finish(self, action: str) -> None:
        self.action = action
        self.accept()
