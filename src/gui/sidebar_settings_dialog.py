"""사이드바 설정 대화 상자."""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
    QDoubleSpinBox, QSpinBox, QLineEdit, QGroupBox,
    QDialogButtonBox, QFormLayout, QComboBox,
)
from PyQt6.QtCore import Qt

from src.data.data_models import GlobalSettings


class SidebarSettingsDialog(QDialog):
    """사이드바 동작·표시 설정 대화 상자."""

    def __init__(self, settings: GlobalSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("사이드바 설정")
        self.setMinimumWidth(400)
        self._settings = settings
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # ── 기본 설정 ──
        basic_group = QGroupBox("기본 설정")
        basic_form = QFormLayout(basic_group)

        self._enabled_cb = QCheckBox()
        self._enabled_cb.setChecked(self._settings.sidebar_enabled)
        basic_form.addRow("사이드바 사용", self._enabled_cb)

        self._height_spin = QDoubleSpinBox()
        self._height_spin.setRange(0.3, 1.0)
        self._height_spin.setSingleStep(0.05)
        self._height_spin.setDecimals(2)
        self._height_spin.setValue(self._settings.sidebar_height_ratio)
        self._height_spin.setToolTip("화면 세로 길이 대비 사이드바 높이 비율 (최소 0.30 = 30%)")
        basic_form.addRow("높이 비율 (0.30~1.00)", self._height_spin)

        self._opacity_spin = QDoubleSpinBox()
        self._opacity_spin.setRange(0.1, 1.0)
        self._opacity_spin.setSingleStep(0.05)
        self._opacity_spin.setDecimals(2)
        self._opacity_spin.setValue(self._settings.sidebar_opacity)
        basic_form.addRow("투명도 (0.10~1.00)", self._opacity_spin)

        self._auto_hide_spin = QSpinBox()
        self._auto_hide_spin.setRange(0, 60000)
        self._auto_hide_spin.setSingleStep(100)
        self._auto_hide_spin.setSuffix(" ms")
        self._auto_hide_spin.setValue(self._settings.sidebar_auto_hide_ms)
        self._auto_hide_spin.setToolTip("0 = 커서가 벗어나는 즉시 숨김\n100ms 단위 조절, 직접 입력 시 1ms 단위")
        basic_form.addRow("자동 숨김 대기", self._auto_hide_spin)

        self._edge_width_spin = QSpinBox()
        self._edge_width_spin.setRange(1, 50)
        self._edge_width_spin.setSuffix(" px")
        self._edge_width_spin.setValue(self._settings.sidebar_edge_width_px)
        self._edge_width_spin.setToolTip("화면 우측 가장자리에서 사이드바를 트리거하는 감지 영역 너비\n값이 클수록 커서를 가장자리에 덜 정확히 위치시켜도 트리거됨")
        basic_form.addRow("엣지 감지 너비", self._edge_width_spin)

        layout.addWidget(basic_group)

        # ── 섹션 사용/미사용 ──
        section_group = QGroupBox("섹션 표시")
        section_form = QFormLayout(section_group)

        self._clock_enabled_cb = QCheckBox()
        self._clock_enabled_cb.setChecked(self._settings.sidebar_clock_enabled)
        section_form.addRow("현재 시간 표시", self._clock_enabled_cb)

        self._playtime_enabled_cb = QCheckBox()
        self._playtime_enabled_cb.setChecked(self._settings.sidebar_playtime_enabled)
        section_form.addRow("플레이타임 표시", self._playtime_enabled_cb)

        self._vol_enabled_cb = QCheckBox()
        self._vol_enabled_cb.setChecked(self._settings.sidebar_volume_section_enabled)
        section_form.addRow("볼륨 섹션 표시", self._vol_enabled_cb)

        layout.addWidget(section_group)

        # ── 현재 시간 설정 ──
        clock_group = QGroupBox("현재 시간 섹션")
        clock_form = QFormLayout(clock_group)

        self._clock_format_edit = QLineEdit(self._settings.sidebar_clock_format)
        self._clock_format_edit.setToolTip(
            "strftime 형식 문자열\n예: %H:%M:%S (24시), %I:%M %p (12시), %Y-%m-%d %H:%M"
        )
        clock_form.addRow("시간 포맷", self._clock_format_edit)

        layout.addWidget(clock_group)

        # ── 플레이타임 설정 ──
        pt_group = QGroupBox("플레이타임 섹션")
        pt_form = QFormLayout(pt_group)

        self._playtime_prefix_edit = QLineEdit(self._settings.sidebar_playtime_prefix)
        pt_form.addRow("접두어 텍스트", self._playtime_prefix_edit)

        layout.addWidget(pt_group)

        # ── 버튼 ──
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_updated_settings(self) -> GlobalSettings:
        """변경된 설정을 반영한 GlobalSettings 를 반환합니다."""
        import copy
        gs = copy.copy(self._settings)
        gs.sidebar_enabled = self._enabled_cb.isChecked()
        gs.sidebar_height_ratio = self._height_spin.value()
        gs.sidebar_opacity = self._opacity_spin.value()
        gs.sidebar_auto_hide_ms = self._auto_hide_spin.value()
        gs.sidebar_edge_width_px = self._edge_width_spin.value()
        gs.sidebar_clock_enabled = self._clock_enabled_cb.isChecked()
        gs.sidebar_clock_format = self._clock_format_edit.text().strip() or "%H:%M:%S"
        gs.sidebar_playtime_enabled = self._playtime_enabled_cb.isChecked()
        gs.sidebar_playtime_prefix = self._playtime_prefix_edit.text().strip()
        gs.sidebar_volume_section_enabled = self._vol_enabled_cb.isChecked()
        return gs
