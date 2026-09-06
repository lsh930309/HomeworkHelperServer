"""PyQt dialog for Beholder data-safety incidents."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QPushButton, QTextEdit, QVBoxLayout


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
