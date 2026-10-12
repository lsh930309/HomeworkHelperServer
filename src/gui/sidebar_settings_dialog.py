"""사이드바 설정 대화 상자."""
import os
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
    QDoubleSpinBox, QSpinBox, QLineEdit, QGroupBox,
    QDialogButtonBox, QFormLayout, QComboBox, QPushButton, QFileDialog,
)
from PySide6.QtCore import Qt, QMetaObject, Slot, Q_ARG

from src.data.data_models import (
    GlobalSettings,
    SIDEBAR_MODE_ALWAYS,
    SIDEBAR_MODE_GAME,
    SIDEBAR_MODE_DISABLED,
    normalize_sidebar_mode,
)


class SidebarSettingsDialog(QDialog):
    """사이드바 동작·표시·스크린샷 설정 대화 상자."""

    def __init__(self, settings: GlobalSettings, parent=None, *, obs_info_provider=None, obs_reconnect=None):
        super().__init__(parent)
        self.setWindowTitle("사이드바 설정")
        self.setMinimumWidth(860)
        self._settings = settings
        self._obs_info_provider = obs_info_provider
        self._obs_reconnect = obs_reconnect
        self._ss_trigger_vk: int = getattr(settings, 'screenshot_trigger_vk', 0xB2)
        self._build_ui()

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(12)

        # ── 2컬럼 레이아웃 ──
        columns = QHBoxLayout()
        columns.setSpacing(12)

        left_col = QVBoxLayout()
        left_col.setSpacing(8)
        right_col = QVBoxLayout()
        right_col.setSpacing(8)

        # ════════════════ 왼쪽 컬럼 ════════════════

        # ── 기본 설정 ──
        basic_group = QGroupBox("기본 설정")
        basic_form = QFormLayout(basic_group)

        self._mode_combo = QComboBox()
        self._mode_combo.addItem("항상 사용", SIDEBAR_MODE_ALWAYS)
        self._mode_combo.addItem("게임 중에만 사용", SIDEBAR_MODE_GAME)
        self._mode_combo.addItem("사용 안함", SIDEBAR_MODE_DISABLED)
        current_mode = normalize_sidebar_mode(
            getattr(self._settings, 'sidebar_mode', None),
            getattr(self._settings, 'sidebar_enabled', True),
        )
        mode_index = self._mode_combo.findData(current_mode)
        self._mode_combo.setCurrentIndex(max(0, mode_index))
        self._mode_combo.setToolTip(
            "항상 사용: 게임 실행 여부와 관계없이 손잡이를 표시\n"
            "게임 중에만 사용: 등록 게임 실행 중에만 손잡이를 표시\n"
            "사용 안함: 손잡이와 사이드바를 숨김"
        )
        basic_form.addRow("사이드바 사용 방식", self._mode_combo)

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

        self._handle_auto_hide_cb = QCheckBox()
        self._handle_auto_hide_cb.setChecked(getattr(self._settings, 'sidebar_handle_auto_hide', True))
        self._handle_auto_hide_cb.setToolTip(
            "켜짐: 평소에는 손잡이를 숨기고 우측 감지 영역에 커서가 들어오면 표시\n"
            "꺼짐: 사이드바가 닫힌 동안 손잡이를 항상 표시"
        )
        basic_form.addRow("손잡이 자동 숨김/등장", self._handle_auto_hide_cb)

        self._edge_width_spin = QSpinBox()
        self._edge_width_spin.setRange(1, 50)
        self._edge_width_spin.setSuffix(" px")
        self._edge_width_spin.setValue(self._settings.sidebar_edge_width_px)
        self._edge_width_spin.setToolTip("화면 우측 가장자리 트리거 감지 영역 너비\n값이 클수록 덜 정밀하게 위치시켜도 트리거됨")
        basic_form.addRow("엣지 감지 너비", self._edge_width_spin)

        self._trigger_y_start_spin = QDoubleSpinBox()
        self._trigger_y_start_spin.setRange(0.0, 1.0)
        self._trigger_y_start_spin.setSingleStep(0.05)
        self._trigger_y_start_spin.setDecimals(2)
        self._trigger_y_start_spin.setValue(getattr(self._settings, 'sidebar_trigger_y_start', 0.1))
        self._trigger_y_start_spin.setToolTip("손잡이를 튀어나오게 할 세로 감지 범위의 시작 비율 (0.00 = 화면 상단)")
        basic_form.addRow("감지 시작 Y", self._trigger_y_start_spin)

        self._trigger_y_end_spin = QDoubleSpinBox()
        self._trigger_y_end_spin.setRange(0.0, 1.0)
        self._trigger_y_end_spin.setSingleStep(0.05)
        self._trigger_y_end_spin.setDecimals(2)
        self._trigger_y_end_spin.setValue(getattr(self._settings, 'sidebar_trigger_y_end', 0.9))
        self._trigger_y_end_spin.setToolTip("손잡이를 튀어나오게 할 세로 감지 범위의 종료 비율 (1.00 = 화면 하단)")
        basic_form.addRow("감지 종료 Y", self._trigger_y_end_spin)

        left_col.addWidget(basic_group)

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

        left_col.addWidget(section_group)

        # ── 현재 시간 설정 ──
        clock_group = QGroupBox("현재 시간 섹션")
        clock_form = QFormLayout(clock_group)

        self._clock_format_edit = QLineEdit(self._settings.sidebar_clock_format)
        self._clock_format_edit.setToolTip(
            "strftime 형식 문자열\n예: %H:%M:%S (24시), %I:%M %p (12시), %Y-%m-%d %H:%M"
        )
        clock_form.addRow("시간 포맷", self._clock_format_edit)

        left_col.addWidget(clock_group)

        # ── 플레이타임 설정 ──
        pt_group = QGroupBox("플레이타임 섹션")
        pt_form = QFormLayout(pt_group)

        self._playtime_prefix_edit = QLineEdit(self._settings.sidebar_playtime_prefix)
        pt_form.addRow("접두어 텍스트", self._playtime_prefix_edit)

        left_col.addWidget(pt_group)
        left_col.addStretch()

        # ════════════════ 오른쪽 컬럼 ════════════════

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
            "게임패드 공유 버튼(Win+Alt+PrtScn)으로 스크린샷 트리거 활성화\n"
            "짧게 누름: 스크린샷 / 길게 누름(800ms+): 녹화 토글"
        )
        ss_form.addRow("게임패드 트리거", self._ss_gamepad_cb)

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

        # 트리거 버튼 매핑
        from src.screenshot.key_capture import vk_to_display_name
        trigger_row = QHBoxLayout()
        self._ss_trigger_label = QLabel(
            f"{vk_to_display_name(self._ss_trigger_vk)} (0x{self._ss_trigger_vk:02X})"
        )
        self._ss_trigger_btn = QPushButton("설정...")
        self._ss_trigger_btn.setFixedWidth(70)
        self._ss_trigger_btn.clicked.connect(self._capture_trigger_key)
        trigger_row.addWidget(self._ss_trigger_label)
        trigger_row.addStretch()
        trigger_row.addWidget(self._ss_trigger_btn)
        ss_form.addRow("트리거 버튼", trigger_row)

        right_col.addWidget(ss_group)

        # ── 녹화 (OBS) 설정 ──
        rec_group = QGroupBox("OBS 연동")
        rec_form = QFormLayout(rec_group)

        self._rec_enabled_cb = QCheckBox()
        self._rec_enabled_cb.setChecked(getattr(self._settings, 'recording_enabled', False))
        rec_form.addRow("녹화 기능 사용", self._rec_enabled_cb)

        self._obs_status_label = QLabel()
        self._obs_exe_label = QLabel()
        self._obs_directory_label = QLabel()
        for label in (self._obs_exe_label, self._obs_directory_label):
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        rec_form.addRow("OBS 상태", self._obs_status_label)
        rec_form.addRow("OBS 실행 파일", self._obs_exe_label)
        rec_form.addRow("녹화 저장 폴더 — OBS 설정", self._obs_directory_label)
        rec_form.addRow("OBS 자동 실행", QLabel("로그온 · 호스트 앱 시작 시 관리자 실행"))
        self._obs_launch_hidden_cb = QCheckBox()
        self._obs_launch_hidden_cb.setChecked(getattr(self._settings, 'obs_launch_hidden', True))
        self._obs_launch_hidden_cb.setToolTip("OBS를 최소화 상태로 실행합니다.")
        rec_form.addRow("  최소화 상태로 실행", self._obs_launch_hidden_cb)

        # 기타
        self._obs_watch_output_cb = QCheckBox()
        self._obs_watch_output_cb.setChecked(getattr(self._settings, 'obs_watch_output_dir', True))
        rec_form.addRow("사이드바에 녹화 파일 표시", self._obs_watch_output_cb)

        self._rec_hold_spin = QSpinBox()
        self._rec_hold_spin.setRange(500, 2000)
        self._rec_hold_spin.setSingleStep(100)
        self._rec_hold_spin.setSuffix(" ms")
        self._rec_hold_spin.setValue(getattr(self._settings, 'recording_hold_threshold_ms', 800))
        self._rec_hold_spin.setToolTip("게임패드 버튼을 이 시간 이상 홀드하면 녹화 토글")
        rec_form.addRow("홀드 임계값", self._rec_hold_spin)

        self._obs_reconnect_btn = QPushButton("다시 연결")
        self._obs_reconnect_btn.setEnabled(self._obs_reconnect is not None)
        self._obs_reconnect_btn.clicked.connect(self._reconnect_obs)
        rec_form.addRow(self._obs_reconnect_btn)
        self._obs_info_note = QLabel()
        self._obs_info_note.setWordWrap(True)
        rec_form.addRow(self._obs_info_note)
        self._rec_enabled_cb.toggled.connect(self.refresh_obs_info)
        self.refresh_obs_info()

        right_col.addWidget(rec_group)
        right_col.addStretch()

        # ── 컬럼 조합 ──
        columns.addLayout(left_col)
        columns.addLayout(right_col)
        main_layout.addLayout(columns)

        # ── 버튼 ──
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)

    def _browse_screenshot_dir(self) -> None:
        current = self._ss_save_dir_edit.text().strip()
        start = current if current and os.path.isdir(current) else str(
            __import__('pathlib').Path.home() / "Pictures"
        )
        chosen = QFileDialog.getExistingDirectory(self, "스크린샷 저장 폴더 선택", start)
        if chosen:
            self._ss_save_dir_edit.setText(chosen)

    @Slot()
    def refresh_obs_info(self, *_args) -> None:
        """Display the manager's observation only; viewing does not launch or connect."""
        info = self._obs_info_provider() if self._obs_info_provider else {}
        state = info.get("state", "obs_offline")
        self._obs_status_label.setText({"idle": "연결됨", "recording": "녹화 중",
                                        "connecting": "연결 중"}.get(state, "연결 안 됨"))
        self._obs_exe_label.setText(info.get("exe_path") or "미확인")
        self._obs_directory_label.setText(info.get("output_dir") or "미확인")
        saved_enabled = info.get("enabled", False)
        selected_enabled = self._rec_enabled_cb.isChecked()
        self._obs_reconnect_btn.setEnabled(self._obs_reconnect is not None and saved_enabled
                                          and selected_enabled and state != "connecting")
        self._obs_reconnect_btn.setToolTip(
            "녹화 기능 사용을 저장한 뒤 다시 연결하세요." if not (saved_enabled and selected_enabled) else ""
        )
        self._obs_info_note.setText(info.get("error") or "녹화 품질과 저장 폴더는 OBS에서 설정합니다.")

    def _reconnect_obs(self) -> None:
        if self._obs_reconnect and self._obs_reconnect_btn.isEnabled():
            self._obs_reconnect()
        self.refresh_obs_info()

    def _capture_trigger_key(self) -> None:
        """'설정...' 버튼 클릭 시 다음 키 입력을 트리거로 등록합니다."""
        self._ss_trigger_btn.setEnabled(False)
        self._ss_trigger_btn.setText("버튼을 누르세요...")

        from src.screenshot.key_capture import capture_one_key
        capture_one_key(
            timeout_sec=10.0,
            on_captured=lambda vk: QMetaObject.invokeMethod(
                self, "_on_trigger_captured",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(int, vk),
            ),
            on_timeout=lambda: QMetaObject.invokeMethod(
                self, "_on_trigger_timeout",
                Qt.ConnectionType.QueuedConnection,
            ),
        )

    @Slot(int)
    def _on_trigger_captured(self, vk: int) -> None:
        from src.screenshot.key_capture import vk_to_display_name
        self._ss_trigger_vk = vk
        self._ss_trigger_label.setText(f"{vk_to_display_name(vk)} (0x{vk:02X})")
        self._ss_trigger_btn.setText("설정...")
        self._ss_trigger_btn.setEnabled(True)

    @Slot()
    def _on_trigger_timeout(self) -> None:
        self._ss_trigger_btn.setText("설정...")
        self._ss_trigger_btn.setEnabled(True)

    def get_updated_settings(self) -> GlobalSettings:
        """변경된 설정을 반영한 GlobalSettings 를 반환합니다."""
        import copy
        gs = copy.copy(self._settings)
        gs.sidebar_mode = self._mode_combo.currentData()
        gs.sidebar_enabled = gs.sidebar_mode != SIDEBAR_MODE_DISABLED
        gs.sidebar_height_ratio = self._height_spin.value()
        gs.sidebar_opacity = self._opacity_spin.value()
        gs.sidebar_auto_hide_ms = self._auto_hide_spin.value()
        gs.sidebar_edge_width_px = self._edge_width_spin.value()
        y_start = self._trigger_y_start_spin.value()
        y_end = self._trigger_y_end_spin.value()
        gs.sidebar_trigger_y_start = min(y_start, y_end)
        gs.sidebar_trigger_y_end = max(y_start, y_end)
        gs.sidebar_handle_auto_hide = self._handle_auto_hide_cb.isChecked()
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
        gs.screenshot_trigger_vk = self._ss_trigger_vk
        # Recording (OBS)
        gs.recording_enabled = self._rec_enabled_cb.isChecked()
        gs.obs_launch_hidden = self._obs_launch_hidden_cb.isChecked()
        gs.obs_watch_output_dir = self._obs_watch_output_cb.isChecked()
        gs.recording_hold_threshold_ms = self._rec_hold_spin.value()
        return gs
