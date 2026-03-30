"""사이드바 설정 대화 상자."""
import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
    QDoubleSpinBox, QSpinBox, QLineEdit, QGroupBox,
    QDialogButtonBox, QFormLayout, QComboBox, QPushButton, QFileDialog,
)
from PyQt6.QtCore import Qt

from src.data.data_models import GlobalSettings


class SidebarSettingsDialog(QDialog):
    """사이드바 동작·표시·스크린샷 설정 대화 상자."""

    def __init__(self, settings: GlobalSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("사이드바 설정")
        self.setMinimumWidth(440)
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
        self._edge_width_spin.setToolTip("화면 우측 가장자리 트리거 감지 영역 너비\n값이 클수록 덜 정밀하게 위치시켜도 트리거됨")
        basic_form.addRow("엣지 감지 너비", self._edge_width_spin)

        layout.addWidget(basic_group)

        # ── 섹션 표시 ──
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

        # ── 스크린샷 설정 ──
        ss_group = QGroupBox("스크린샷")
        ss_form = QFormLayout(ss_group)

        self._ss_enabled_cb = QCheckBox()
        self._ss_enabled_cb.setChecked(self._settings.screenshot_enabled)
        ss_form.addRow("스크린샷 기능 사용", self._ss_enabled_cb)

        # 저장 경로
        save_dir_row = QHBoxLayout()
        self._ss_save_dir_edit = QLineEdit(self._settings.screenshot_save_dir)
        self._ss_save_dir_edit.setPlaceholderText("비워두면 기본 경로 사용 (~/Pictures/GameCaptures)")
        browse_btn = QPushButton("찾기...")
        browse_btn.setFixedWidth(60)
        browse_btn.clicked.connect(self._browse_screenshot_dir)
        save_dir_row.addWidget(self._ss_save_dir_edit)
        save_dir_row.addWidget(browse_btn)
        ss_form.addRow("저장 경로", save_dir_row)

        # 게임패드 트리거
        self._ss_gamepad_cb = QCheckBox()
        self._ss_gamepad_cb.setChecked(self._settings.screenshot_gamepad_trigger)
        self._ss_gamepad_cb.setToolTip(
            "게임패드 버튼으로 스크린샷 트리거 활성화\n"
            "버튼 인덱스는 tools/diagnose_gamepad_screenshot.py 로 탐색"
        )
        ss_form.addRow("게임패드 트리거", self._ss_gamepad_cb)

        # 감지된 버튼 인덱스 표시 (읽기 전용)
        btn_idx = self._settings.screenshot_gamepad_button_index
        btn_idx_label = QLabel(
            str(btn_idx) if btn_idx >= 0 else "미설정 (진단 도구 실행 필요)"
        )
        btn_idx_label.setStyleSheet("color: gray; font-size: 11px;")
        ss_form.addRow("감지된 버튼 인덱스", btn_idx_label)

        # Game Bar 캡처 비활성화
        self._ss_disable_gamebar_cb = QCheckBox()
        self._ss_disable_gamebar_cb.setChecked(self._settings.screenshot_disable_gamebar)
        self._ss_disable_gamebar_cb.setToolTip(
            "앱 실행 시 Game Bar 스크린샷 캡처를 비활성화합니다.\n"
            "레지스트리: HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\GameDVR\\AppCaptureEnabled = 0\n"
            "앱 종료 시 원래 값으로 복원됩니다."
        )
        ss_form.addRow("Game Bar 캡처 비활성화", self._ss_disable_gamebar_cb)

        # 캡처 대상
        self._ss_capture_mode_combo = QComboBox()
        self._ss_capture_mode_combo.addItem("전체 화면", "fullscreen")
        self._ss_capture_mode_combo.addItem("포커스된 게임 창 (렌더링 영역)", "game_window")
        idx = self._ss_capture_mode_combo.findData(self._settings.screenshot_capture_mode)
        if idx >= 0:
            self._ss_capture_mode_combo.setCurrentIndex(idx)
        ss_form.addRow("캡처 대상", self._ss_capture_mode_combo)

        layout.addWidget(ss_group)

        # ── 버튼 ──
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse_screenshot_dir(self) -> None:
        current = self._ss_save_dir_edit.text().strip()
        start = current if current and os.path.isdir(current) else str(
            __import__('pathlib').Path.home() / "Pictures"
        )
        chosen = QFileDialog.getExistingDirectory(self, "스크린샷 저장 폴더 선택", start)
        if chosen:
            self._ss_save_dir_edit.setText(chosen)

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
        gs.screenshot_enabled = self._ss_enabled_cb.isChecked()
        gs.screenshot_save_dir = self._ss_save_dir_edit.text().strip()
        gs.screenshot_gamepad_trigger = self._ss_gamepad_cb.isChecked()
        gs.screenshot_disable_gamebar = self._ss_disable_gamebar_cb.isChecked()
        gs.screenshot_capture_mode = self._ss_capture_mode_combo.currentData()
        return gs
