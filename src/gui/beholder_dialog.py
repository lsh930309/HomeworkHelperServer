"""PyQt dialog for Beholder data-safety incidents."""

from __future__ import annotations

from typing import Any

from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QPushButton, QTextEdit, QVBoxLayout


class BeholderIncidentDialog(QDialog):
    def __init__(self, incident: dict[str, Any], parent=None):
        super().__init__(parent)
        self.incident = incident
        self.action: str = "deny"
        self.setWindowTitle("Beholder 데이터 보호 안내")
        self.setMinimumWidth(560)

        title = QLabel(incident.get("user_title") or "데이터 변경 확인이 필요합니다")
        title.setStyleSheet("font-size: 17px; font-weight: 800; color: #f3d27a;")

        lead = QLabel(incident.get("user_summary") or "Beholder가 저장 전에 변경 내용을 확인했습니다.")
        lead.setWordWrap(True)

        severity = incident.get("severity", "warning")
        risk = incident.get("risk_score", 0)
        summary = QTextEdit()
        summary.setReadOnly(True)
        summary.setMinimumHeight(250)
        factors = incident.get("risk_factors") or []
        factor_text = "\n".join(f"- {item}" for item in factors) or "- 없음"
        summary.setPlainText(
            f"사용자 영향\n{incident.get('user_impact') or '-'}\n\n"
            f"권장 조치\n{incident.get('safe_recommendation') or '차단을 유지하세요.'}\n\n"
            f"심각도: {severity} / 위험도: {risk}/100\n"
            f"동작: {incident.get('operation_kind')} / {incident.get('actor')}\n\n"
            f"현재 DB 상태\n{incident.get('current_state_summary') or '-'}\n\n"
            f"저장하려던 변경\n{incident.get('proposed_change_summary') or '-'}\n\n"
            f"위험 신호\n{factor_text}"
        )

        buttons = QDialogButtonBox()
        actions = incident.get("available_actions") or []
        if not actions:
            actions = [
                {"id": "deny", "label": "차단 유지"},
                {"id": "quarantine", "label": "격리"},
                {"id": "allow_once", "label": "이번 한 번 허용"},
            ]
        for action in actions:
            action_id = action.get("id")
            if not action_id:
                continue
            label = action.get("label") or action_id
            if action.get("recommended"):
                label = f"★ {label}"
            button = QPushButton(label)
            button.setToolTip(action.get("description") or "")
            role = QDialogButtonBox.ButtonRole.AcceptRole if action.get("recommended") else QDialogButtonBox.ButtonRole.ActionRole
            if action.get("danger"):
                role = QDialogButtonBox.ButtonRole.DestructiveRole
            if action_id == "deny":
                role = QDialogButtonBox.ButtonRole.RejectRole
            buttons.addButton(button, role)
            button.clicked.connect(lambda _checked=False, selected=action_id: self._finish(selected))
        restore = QPushButton("백업에서 복구")
        buttons.addButton(restore, QDialogButtonBox.ButtonRole.DestructiveRole)
        restore.clicked.connect(lambda: self._finish("restore_backup"))

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(lead)
        layout.addWidget(summary)
        layout.addWidget(buttons)

    def _finish(self, action: str) -> None:
        self.action = action
        self.accept()
