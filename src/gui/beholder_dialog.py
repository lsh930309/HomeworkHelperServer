"""PyQt dialog for Beholder data-safety incidents."""

from __future__ import annotations

from typing import Any

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)


class BeholderIncidentDialog(QDialog):
    def __init__(self, incident: dict[str, Any], parent=None):
        super().__init__(parent)
        self.incident = incident
        self.action: str = "deny"
        self.setWindowTitle("Beholder 데이터 보호 경고")
        self.setMinimumWidth(520)

        title = QLabel("비정상 데이터 변경이 차단되었습니다")
        title.setStyleSheet("font-size: 16px; font-weight: 700;")

        severity = incident.get("severity", "warning")
        risk = incident.get("risk_score", 0)
        summary = QTextEdit()
        summary.setReadOnly(True)
        summary.setMinimumHeight(260)
        factors = incident.get("risk_factors") or []
        factor_text = "\n".join(f"- {item}" for item in factors) or "- 없음"
        summary.setPlainText(
            f"심각도: {severity}\n"
            f"위험도: {risk}/100\n"
            f"동작: {incident.get('operation_kind')} / {incident.get('actor')}\n\n"
            f"의심 원인\n{incident.get('suspected_cause') or '-'}\n\n"
            f"현재 DB 상태\n{incident.get('current_state_summary') or '-'}\n\n"
            f"허용 시 변경\n{incident.get('proposed_change_summary') or '-'}\n\n"
            f"위험 신호\n{factor_text}\n\n"
            f"권장 조치\n{incident.get('safe_recommendation') or '차단을 유지하세요.'}"
        )

        buttons = QDialogButtonBox()
        deny = QPushButton("차단 유지")
        quarantine = QPushButton("격리")
        allow = QPushButton("이번 한 번 허용")
        restore = QPushButton("백업에서 복구")
        buttons.addButton(deny, QDialogButtonBox.ButtonRole.RejectRole)
        buttons.addButton(quarantine, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(allow, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(restore, QDialogButtonBox.ButtonRole.DestructiveRole)
        deny.clicked.connect(lambda: self._finish("deny"))
        quarantine.clicked.connect(lambda: self._finish("quarantine"))
        allow.clicked.connect(lambda: self._finish("allow_once"))
        restore.clicked.connect(lambda: self._finish("restore_backup"))

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(QLabel("Beholder가 DB에 급격한 변화가 생길 수 있는 요청을 커밋 전에 막았습니다."))
        layout.addWidget(summary)
        layout.addWidget(buttons)

    def _finish(self, action: str) -> None:
        self.action = action
        self.accept()
