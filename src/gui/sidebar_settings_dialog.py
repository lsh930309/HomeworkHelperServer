"""사이드바 설정 대화 상자."""
import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
    QDoubleSpinBox, QSpinBox, QLineEdit, QGroupBox,
    QDialogButtonBox, QFormLayout, QComboBox, QPushButton, QFileDialog,
    QScrollArea, QApplication,
)
from PyQt6.QtCore import Qt

from src.data.data_models import GlobalSettings


class SidebarSettingsDialog(QDialog):
    """사이드바 동작·표시·스크린샷 설정 대화 상자."""

    def __init__(self, settings: GlobalSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("사이드바 설정")
        self.resize(760, 700)
        self.setMinimumSize(700, 520)
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            self.setMaximumSize(max(700, available.width() - 80), max(520, available.height() - 80))
        self._settings = settings
        self._build_ui()

    def _build_ui(self) -> None:
        outer_layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer_layout.addWidget(scroll)

        content = QWidget()
        main_layout = QVBoxLayout(content)
        main_layout.setSpacing(12)
        scroll.setWidget(content)

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

        right_col.addWidget(ss_group)

        # ── 녹화 (OBS) 설정 ──
        rec_group = QGroupBox("녹화 (OBS)")
        rec_form = QFormLayout(rec_group)

        self._rec_enabled_cb = QCheckBox()
        self._rec_enabled_cb.setChecked(getattr(self._settings, 'recording_enabled', False))
        rec_form.addRow("녹화 기능 사용", self._rec_enabled_cb)

        # 연결 설정
        self._obs_host_edit = QLineEdit(getattr(self._settings, 'obs_host', 'localhost'))
        self._obs_host_edit.setPlaceholderText("localhost")
        rec_form.addRow("OBS 호스트", self._obs_host_edit)

        self._obs_port_spin = QSpinBox()
        self._obs_port_spin.setRange(1, 65535)
        self._obs_port_spin.setValue(getattr(self._settings, 'obs_port', 4455))
        rec_form.addRow("OBS 포트", self._obs_port_spin)

        self._obs_password_edit = QLineEdit(getattr(self._settings, 'obs_password', ''))
        self._obs_password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._obs_password_edit.setPlaceholderText("비밀번호 없으면 비워두세요")
        rec_form.addRow("OBS 비밀번호", self._obs_password_edit)

        # OBS 자동 실행
        obs_exe_row = QHBoxLayout()
        self._obs_exe_edit = QLineEdit(getattr(self._settings, 'obs_exe_path', ''))
        self._obs_exe_edit.setPlaceholderText("obs64.exe 경로")
        obs_exe_browse_btn = QPushButton("찾기...")
        obs_exe_browse_btn.setFixedWidth(60)
        obs_exe_browse_btn.clicked.connect(self._browse_obs_exe)
        obs_exe_row.addWidget(self._obs_exe_edit)
        obs_exe_row.addWidget(obs_exe_browse_btn)
        rec_form.addRow("OBS 실행 파일", obs_exe_row)

        self._obs_auto_launch_cb = QCheckBox()
        self._obs_auto_launch_cb.setChecked(getattr(self._settings, 'obs_auto_launch', False))
        self._obs_auto_launch_cb.setToolTip("녹화 시 OBS가 실행 중이 아니면 자동으로 실행합니다.")
        rec_form.addRow("OBS 자동 실행", self._obs_auto_launch_cb)

        self._obs_launch_hidden_cb = QCheckBox()
        self._obs_launch_hidden_cb.setChecked(getattr(self._settings, 'obs_launch_hidden', True))
        self._obs_launch_hidden_cb.setToolTip("OBS를 최소화 상태로 실행합니다.")
        self._obs_auto_launch_cb.toggled.connect(self._obs_launch_hidden_cb.setEnabled)
        self._obs_launch_hidden_cb.setEnabled(self._obs_auto_launch_cb.isChecked())
        rec_form.addRow("  최소화 상태로 실행", self._obs_launch_hidden_cb)

        # 기타
        self._obs_watch_output_cb = QCheckBox()
        self._obs_watch_output_cb.setChecked(getattr(self._settings, 'obs_watch_output_dir', True))
        rec_form.addRow("출력 폴더 감시", self._obs_watch_output_cb)

        self._rec_hold_spin = QSpinBox()
        self._rec_hold_spin.setRange(100, 2000)
        self._rec_hold_spin.setSingleStep(100)
        self._rec_hold_spin.setSuffix(" ms")
        self._rec_hold_spin.setValue(getattr(self._settings, 'recording_hold_threshold_ms', 800))
        self._rec_hold_spin.setToolTip("게임패드 버튼을 이 시간 이상 홀드하면 녹화 토글")
        rec_form.addRow("홀드 임계값", self._rec_hold_spin)

        # OBS에서 불러오기 버튼
        obs_import_btn = QPushButton("OBS에서 불러오기")
        obs_import_btn.setToolTip("로컬 OBS 설정에서 포트/비밀번호/실행 경로를 자동으로 읽어옵니다.")
        obs_import_btn.clicked.connect(self._import_obs_config)
        rec_form.addRow(obs_import_btn)

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
        outer_layout.addWidget(buttons)

    def _browse_screenshot_dir(self) -> None:
        current = self._ss_save_dir_edit.text().strip()
        start = current if current and os.path.isdir(current) else str(
            __import__('pathlib').Path.home() / "Pictures"
        )
        chosen = QFileDialog.getExistingDirectory(self, "스크린샷 저장 폴더 선택", start)
        if chosen:
            self._ss_save_dir_edit.setText(chosen)

    def _browse_obs_exe(self) -> None:
        current = self._obs_exe_edit.text().strip()
        start_dir = os.path.dirname(current) if current and os.path.isfile(current) else "C:\\Program Files"
        chosen, _ = QFileDialog.getOpenFileName(
            self, "OBS 실행 파일 선택", start_dir, "실행 파일 (*.exe)"
        )
        if chosen:
            self._obs_exe_edit.setText(chosen)

    def _import_obs_config(self) -> None:
        try:
            from src.recording.obs_config_reader import read_obs_config
            cfg = read_obs_config()
            self._obs_port_spin.setValue(cfg["port"])
            self._obs_password_edit.setText(cfg["password"])
            if cfg["exe_path"]:
                self._obs_exe_edit.setText(cfg["exe_path"])
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "OBS 설정 불러오기", f"OBS 설정을 읽지 못했습니다:\n{e}")

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
        # Recording (OBS)
        gs.recording_enabled = self._rec_enabled_cb.isChecked()
        gs.obs_host = self._obs_host_edit.text().strip() or "localhost"
        gs.obs_port = self._obs_port_spin.value()
        gs.obs_password = self._obs_password_edit.text()
        gs.obs_exe_path = self._obs_exe_edit.text().strip()
        gs.obs_auto_launch = self._obs_auto_launch_cb.isChecked()
        gs.obs_launch_hidden = self._obs_launch_hidden_cb.isChecked()
        gs.obs_watch_output_dir = self._obs_watch_output_cb.isChecked()
        gs.recording_hold_threshold_ms = self._rec_hold_spin.value()
        return gs
