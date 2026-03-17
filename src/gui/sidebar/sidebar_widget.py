"""게임 실행 중 우측에서 슬라이드인하는 사이드바 위젯.

QPropertyAnimation 으로 부드러운 슬라이드 효과를 제공하며,
볼륨 슬라이더, 스태미나 바, 플레이 시간, 게임 제어 버튼을 포함합니다.
"""
import logging
import time
from typing import Optional

from PyQt6.QtCore import (
    Qt, QPropertyAnimation, QEasingCurve, QRect, QTimer, QPoint,
    QRunnable, QThreadPool, QObject, pyqtSignal,
)
from PyQt6.QtGui import QScreen, QColor
from PyQt6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QScrollArea, QSizePolicy, QSlider, QVBoxLayout, QWidget,
)

from src.data.data_models import ManagedProcess
from src.utils import audio_control

logger = logging.getLogger(__name__)

# 사이드바 고정 너비 (px)
_SIDEBAR_WIDTH = 240
# 슬라이드 애니메이션 시간 (ms)
_ANIM_DURATION_MS = 220
# 자동 숨김 타이머 기본값 (ms) — SidebarController 가 override 함
_DEFAULT_AUTO_HIDE_MS = 3000

def _tint_icon_white(icon) -> "QIcon":
    """아이콘 픽셀을 흰색으로 틴팅합니다 (다크 배경 전용)."""
    from PyQt6.QtGui import QPainter, QColor, QPixmap
    from PyQt6.QtCore import Qt
    pixmap = icon.pixmap(16, 16)
    if pixmap.isNull():
        return icon
    result = QPixmap(pixmap.size())
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    painter.drawPixmap(0, 0, pixmap)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(result.rect(), QColor("white"))
    painter.end()
    from PyQt6.QtGui import QIcon
    return QIcon(result)


# 슬라이더 스타일 (volume_panel.py 와 동일 스타일)
_SLIDER_STYLE = """
QSlider::groove:horizontal {
    height: 5px;
    background: palette(midlight);
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: palette(highlight);
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: palette(light);
    border: 2px solid palette(highlight);
    width: 14px;
    height: 14px;
    border-radius: 7px;
    margin: -5px 0;
}
QSlider::handle:horizontal:hover {
    background: palette(highlight);
    border-color: palette(highlight);
}
"""


class SidebarWidget(QWidget):
    """게임 오버레이 사이드바 위젯.

    화면 우측에서 슬라이드인하며, 포커스를 빼앗지 않습니다.
    """

    def __init__(
        self,
        data_manager,
        auto_hide_ms: int = _DEFAULT_AUTO_HIDE_MS,
        screen: Optional[QScreen] = None,
        parent: Optional[QWidget] = None,
    ):
        """SidebarWidget 을 초기화합니다.

        Args:
            data_manager: ApiClient 인스턴스 (볼륨 저장 등에 사용).
            auto_hide_ms: 마지막 상호작용 후 자동 숨김까지 대기 시간 (ms).
            screen: 표시할 화면. None 이면 주 화면을 사용합니다.
            parent: 부모 위젯.
        """
        super().__init__(
            parent,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self._data_manager = data_manager
        self._auto_hide_ms = auto_hide_ms
        self._current_process: Optional[ManagedProcess] = None
        self._current_pid: Optional[int] = None
        self._game_start_timestamp: Optional[float] = None
        self._is_shown = False

        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(_SIDEBAR_WIDTH)

        # 대상 화면
        self._screen = screen or QApplication.primaryScreen()

        # 내부 프레임 (반투명 배경 + 테두리)
        self._frame = QFrame(self)
        self._frame.setObjectName("SidebarFrame")
        self._frame.setStyleSheet("""
            QFrame#SidebarFrame {
                background-color: rgba(30, 30, 30, 210);
                border-left: 1px solid rgba(255, 255, 255, 40);
                border-radius: 0px;
            }
        """)
        frame_layout = QVBoxLayout(self._frame)
        frame_layout.setContentsMargins(12, 16, 12, 16)
        frame_layout.setSpacing(10)

        self._build_ui(frame_layout)

        # 슬라이드 애니메이션
        self._anim = QPropertyAnimation(self, b"geometry")
        self._anim.setDuration(_ANIM_DURATION_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        # 자동 숨김 타이머
        self._auto_hide_timer = QTimer(self)
        self._auto_hide_timer.setSingleShot(True)
        self._auto_hide_timer.timeout.connect(self.slide_out)

        # 플레이 시간 갱신 타이머 (1초)
        self._playtime_timer = QTimer(self)
        self._playtime_timer.setInterval(1000)
        self._playtime_timer.timeout.connect(self._refresh_playtime)

        # 볼륨 저장 전용 직렬 스레드풀 (VolumePopoverPanel 와 동일 패턴)
        self._volume_save_timers: dict = {}
        self._save_pool = QThreadPool(self)
        self._save_pool.setMaxThreadCount(1)

        # Win32 블러 효과 적용 (창이 표시된 뒤 winId 획득 후 적용)
        self._blur_applied = False

    # ------------------------------------------------------------------
    # UI 구성
    # ------------------------------------------------------------------

    def _build_ui(self, layout: QVBoxLayout) -> None:
        """사이드바 내부 위젯을 구성합니다."""
        # --- 게임 아이콘 + 이름 헤더 ---
        header_row = QHBoxLayout()
        header_row.setSpacing(8)

        self._game_icon_label = QLabel()
        self._game_icon_label.setFixedSize(40, 40)
        self._game_icon_label.setStyleSheet(
            "background: rgba(255,255,255,15); border-radius: 8px;"
        )
        self._game_icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._game_icon_label.setScaledContents(True)
        header_row.addWidget(self._game_icon_label)

        self._game_name_label = QLabel("게임")
        self._game_name_label.setStyleSheet(
            "color: white; font-weight: bold; font-size: 13px;"
        )
        self._game_name_label.setWordWrap(True)
        header_row.addWidget(self._game_name_label, 1)
        layout.addLayout(header_row)

        # --- 볼륨 섹션 (모든 등록 게임) ---
        vol_title = QLabel("볼륨")
        vol_title.setStyleSheet("color: rgba(255,255,255,160); font-size: 11px;")
        layout.addWidget(vol_title)

        self._vol_scroll = QScrollArea()
        self._vol_scroll.setWidgetResizable(True)
        self._vol_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._vol_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._vol_scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
            "QWidget#vol_container { background: transparent; }"
        )
        self._vol_list_container = QWidget()
        self._vol_list_container.setObjectName("vol_container")
        self._vol_list_layout = QVBoxLayout(self._vol_list_container)
        self._vol_list_layout.setContentsMargins(0, 0, 4, 0)
        self._vol_list_layout.setSpacing(4)
        self._vol_scroll.setWidget(self._vol_list_container)
        layout.addWidget(self._vol_scroll)

        # --- 스태미나 섹션 ---
        self._stamina_section = QWidget()
        stamina_layout = QVBoxLayout(self._stamina_section)
        stamina_layout.setContentsMargins(0, 0, 0, 0)
        stamina_layout.setSpacing(4)

        stamina_title = QLabel("스태미나")
        stamina_title.setStyleSheet("color: rgba(255,255,255,160); font-size: 11px;")
        stamina_layout.addWidget(stamina_title)

        self._stamina_bar = QProgressBar()
        self._stamina_bar.setRange(0, 100)
        self._stamina_bar.setValue(0)
        self._stamina_bar.setFixedHeight(10)
        self._stamina_bar.setTextVisible(False)
        self._stamina_bar.setStyleSheet("""
            QProgressBar {
                background: rgba(255,255,255,40);
                border-radius: 5px;
            }
            QProgressBar::chunk {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #4fc3f7, stop:1 #0288d1
                );
                border-radius: 5px;
            }
        """)
        stamina_layout.addWidget(self._stamina_bar)

        self._stamina_label = QLabel("—")
        self._stamina_label.setStyleSheet("color: white; font-size: 11px;")
        stamina_layout.addWidget(self._stamina_label)

        layout.addWidget(self._stamina_section)
        self._stamina_section.setVisible(False)

        # --- 플레이 시간 섹션 ---
        playtime_title = QLabel("오늘 플레이")
        playtime_title.setStyleSheet("color: rgba(255,255,255,160); font-size: 11px;")
        layout.addWidget(playtime_title)

        self._playtime_label = QLabel("00:00:00")
        self._playtime_label.setStyleSheet(
            "color: white; font-size: 14px; font-weight: bold;"
        )
        layout.addWidget(self._playtime_label)

        # --- 여백 ---
        layout.addStretch(1)

        # --- 닫기 버튼 ---
        close_btn = QPushButton("닫기")
        close_btn.setFixedHeight(28)
        close_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,30);
                color: white;
                border: 1px solid rgba(255,255,255,60);
                border-radius: 4px;
                font-size: 11px;
            }
            QPushButton:hover {
                background: rgba(255,255,255,60);
            }
        """)
        close_btn.clicked.connect(self.slide_out)
        layout.addWidget(close_btn)

    @staticmethod
    def _make_separator() -> QFrame:
        """얇은 수평 구분선을 반환합니다."""
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background: rgba(255,255,255,30); max-height: 1px;")
        return line

    # ------------------------------------------------------------------
    # 공개 API
    # ------------------------------------------------------------------

    def update_process(
        self,
        process: Optional[ManagedProcess],
        pid: Optional[int] = None,
        game_start_timestamp: Optional[float] = None,
    ) -> None:
        """표시할 프로세스 정보를 갱신합니다."""
        self._current_process = process
        self._current_pid = pid
        self._game_start_timestamp = game_start_timestamp

        if process is None:
            self._game_name_label.setText("게임")
            self._game_icon_label.clear()
            self._refresh_volumes_list()
            self._stamina_section.setVisible(False)
            self._playtime_label.setText("0분")
            return

        self._game_name_label.setText(process.name)

        # 고해상도 아이콘 로드 (백그라운드 스레드로 캐시 추출 후 UI 갱신)
        self._load_icon_async(process)

        # 모든 게임 볼륨 목록 갱신
        self._refresh_volumes_list()

        # 스태미나
        self._refresh_stamina(process)

        # 플레이 시간
        self._refresh_playtime()

    def update_auto_hide_ms(self, ms: int) -> None:
        """자동 숨김 대기 시간을 갱신합니다."""
        self._auto_hide_ms = ms

    def slide_in(self) -> None:
        """사이드바를 화면 우측에서 슬라이드인합니다."""
        if self._is_shown:
            self._reset_auto_hide()
            return

        geo = self._compute_geometry()
        # 시작 위치: 화면 밖 우측
        start = QRect(geo.x() + _SIDEBAR_WIDTH, geo.y(), geo.width(), geo.height())

        self.setGeometry(start)
        self.show()

        # Win32 블러 효과 (최초 한 번만)
        if not self._blur_applied:
            self._try_apply_blur()

        self._anim.setStartValue(start)
        self._anim.setEndValue(geo)
        self._anim.start()

        self._is_shown = True
        self._playtime_timer.start()
        self._refresh_volumes_list()  # 슬라이드인 시 PID 새로 조회
        self._reset_auto_hide()
        logger.debug("SidebarWidget 슬라이드인")

    def slide_out(self) -> None:
        """사이드바를 화면 우측으로 슬라이드아웃합니다."""
        if not self._is_shown:
            return

        self._auto_hide_timer.stop()
        self._playtime_timer.stop()

        geo = self.geometry()
        end = QRect(geo.x() + _SIDEBAR_WIDTH, geo.y(), geo.width(), geo.height())

        self._anim.setStartValue(geo)
        self._anim.setEndValue(end)
        self._anim.finished.connect(self._on_slide_out_finished)
        self._anim.start()

        self._is_shown = False
        logger.debug("SidebarWidget 슬라이드아웃")

    def cleanup(self) -> None:
        """타이머와 애니메이션을 정리합니다."""
        self._auto_hide_timer.stop()
        self._playtime_timer.stop()
        self._anim.stop()
        self.hide()

    # ------------------------------------------------------------------
    # 이벤트 오버라이드
    # ------------------------------------------------------------------

    def resizeEvent(self, event) -> None:
        """위젯 크기 변경 시 내부 프레임을 동기화합니다."""
        super().resizeEvent(event)
        self._frame.setGeometry(0, 0, self.width(), self.height())

    def enterEvent(self, event) -> None:
        """마우스가 사이드바에 진입하면 자동 숨김 타이머를 취소합니다."""
        super().enterEvent(event)
        self._auto_hide_timer.stop()

    def leaveEvent(self, event) -> None:
        """마우스가 사이드바에서 벗어나면 자동 숨김 타이머를 시작합니다.

        자식 위젯으로 이동할 때도 부모의 leaveEvent가 발생하므로,
        커서가 실제로 위젯 영역 밖인지 확인한 후 타이머를 시작합니다.
        """
        super().leaveEvent(event)
        from PyQt6.QtGui import QCursor
        if not self.rect().contains(self.mapFromGlobal(QCursor.pos())):
            self._reset_auto_hide()

    # ------------------------------------------------------------------
    # 내부 메서드
    # ------------------------------------------------------------------

    def _compute_geometry(self) -> QRect:
        """사이드바가 화면 우측에 맞붙는 QRect 을 계산합니다."""
        screen = self._screen or QApplication.primaryScreen()
        if screen is None:
            return QRect(0, 0, _SIDEBAR_WIDTH, 600)
        geo = screen.availableGeometry()
        x = geo.right() - _SIDEBAR_WIDTH + 1
        y = geo.top()
        h = geo.height()
        return QRect(x, y, _SIDEBAR_WIDTH, h)

    def _reset_auto_hide(self) -> None:
        """자동 숨김 타이머를 초기화합니다."""
        if self._auto_hide_ms > 0:
            self._auto_hide_timer.start(self._auto_hide_ms)

    def _on_slide_out_finished(self) -> None:
        """슬라이드아웃 완료 후 창을 숨깁니다."""
        try:
            self._anim.finished.disconnect(self._on_slide_out_finished)
        except (RuntimeError, TypeError):
            pass
        self.hide()

    def _try_apply_blur(self) -> None:
        """Win32 블러/반투명 효과를 창에 적용합니다."""
        try:
            from src.gui.sidebar.win32_effects import apply_blur_effect
            hwnd = int(self.winId())
            effect = "acrylic"
            if self._data_manager and hasattr(self._data_manager, 'global_settings'):
                effect = getattr(self._data_manager.global_settings, 'sidebar_effect', 'acrylic')
            self._blur_applied = apply_blur_effect(hwnd, effect)
            if self._blur_applied:
                logger.debug("사이드바 블러 효과 적용됨 (effect=%s)", effect)
        except Exception:
            logger.debug("사이드바 블러 효과 적용 실패", exc_info=True)

    def _refresh_stamina(self, process: ManagedProcess) -> None:
        """스태미나 섹션을 갱신합니다."""
        stamina_info = process.get_predicted_stamina() if process.is_hoyoverse_game() else None
        if stamina_info is None:
            self._stamina_section.setVisible(False)
            return

        current, maximum = stamina_info
        self._stamina_section.setVisible(True)
        pct = int((current / maximum) * 100) if maximum > 0 else 0
        self._stamina_bar.setValue(pct)
        self._stamina_label.setText(f"{current} / {maximum}")

    def _refresh_playtime(self) -> None:
        """플레이 시간 레이블을 갱신합니다."""
        if self._game_start_timestamp is None:
            self._playtime_label.setText("0분")
            return
        elapsed = int(time.time() - self._game_start_timestamp)
        h = elapsed // 3600
        m = (elapsed % 3600) // 60
        if h > 0:
            self._playtime_label.setText(f"{h}시간 {m:02d}분")
        else:
            self._playtime_label.setText(f"{m}분")

    def _load_icon_async(self, process: ManagedProcess) -> None:
        """게임 아이콘을 백그라운드 스레드에서 추출한 뒤 UI에 반영합니다."""
        from PyQt6.QtCore import QThread, pyqtSignal as Signal

        class _IconLoader(QThread):
            icon_loaded = Signal(object)  # QPixmap

            def __init__(self, path: str, parent=None):
                super().__init__(parent)
                self._path = path

            def run(self):
                try:
                    from src.utils.process import get_qicon_for_file
                    icon = get_qicon_for_file(self._path, icon_size=48)
                    if icon and not icon.isNull():
                        self.icon_loaded.emit(icon.pixmap(40, 40))
                except Exception:
                    pass

        loader = _IconLoader(process.monitoring_path, self)

        def _on_icon(pixmap):
            if not pixmap.isNull():
                self._game_icon_label.setPixmap(pixmap)
            loader.deleteLater()

        loader.icon_loaded.connect(_on_icon)
        loader.start()

        # 스태미나도 주기적으로 갱신
        if self._current_process is not None:
            self._refresh_stamina(self._current_process)

    def _refresh_volumes_list(self) -> None:
        """모든 등록 게임에 대한 볼륨 행을 재구성합니다."""
        # 기존 행 제거
        while self._vol_list_layout.count() > 0:
            item = self._vol_list_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        processes = getattr(self._data_manager, 'managed_processes', [])
        if not processes:
            empty = QLabel("등록된 게임 없음")
            empty.setStyleSheet("color: rgba(255,255,255,100); font-size: 11px;")
            self._vol_list_layout.addWidget(empty)
            return

        # 현재 실행 중인 PID 맵
        from src.gui.main_window import MainWindow
        active_pids: dict = {}
        if MainWindow.INSTANCE:
            active_pids = {
                proc_id: entry.get('pid')
                for proc_id, entry in MainWindow.INSTANCE.process_monitor.active_monitored_processes.items()
            }

        for proc in processes:
            self._vol_list_layout.addWidget(self._make_vol_row(proc, active_pids.get(proc.id)))

    def _make_vol_row(self, process: ManagedProcess, pid: Optional[int]) -> QWidget:
        """다크 테마 볼륨 행 (이름 + 음소거 버튼 + 슬라이더 + 값 레이블)."""
        is_running = pid is not None
        row = QWidget()
        # 실행 중인 게임은 행 배경을 살짝 밝힘
        row_bg = "rgba(255,255,255,12)" if is_running else "transparent"
        row.setStyleSheet(f"background: {row_bg}; border-radius: 3px;")
        hl = QHBoxLayout(row)
        hl.setContentsMargins(4, 2, 4, 2)
        hl.setSpacing(4)

        # 실행 중 인디케이터: 녹색 점
        dot_lbl = QLabel("●")
        dot_lbl.setFixedWidth(10)
        dot_lbl.setStyleSheet(
            "color: #4caf50; font-size: 8px;" if is_running
            else "color: transparent; font-size: 8px;"
        )
        hl.addWidget(dot_lbl)

        name_lbl = QLabel(process.name)
        name_lbl.setStyleSheet("color: rgba(255,255,255,220); font-size: 11px;")
        name_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        hl.addWidget(name_lbl, 1)

        # 음소거 버튼 (실행 중/대기 중 모두 활성화)
        mute_btn = QPushButton()
        mute_btn.setFixedSize(22, 22)
        mute_btn.setCheckable(True)
        mute_btn.setStyleSheet("""
            QPushButton {
                border: 1px solid rgba(255,255,255,60);
                border-radius: 3px;
                background: rgba(255,255,255,20);
                color: white;
                font-size: 10px;
            }
            QPushButton:checked {
                background: rgba(100,149,237,180);
                border-color: rgba(100,149,237,255);
                color: white;
            }
            QPushButton:hover:!checked {
                background: rgba(255,255,255,40);
            }
        """)

        from PyQt6.QtWidgets import QApplication, QStyle
        style = QApplication.style()
        if style:
            icon_on = style.standardIcon(QStyle.StandardPixmap.SP_MediaVolume)
            icon_off = style.standardIcon(QStyle.StandardPixmap.SP_MediaVolumeMuted)
            if not icon_on.isNull():
                icon_on_w = _tint_icon_white(icon_on)
                icon_off_w = _tint_icon_white(icon_off) if not icon_off.isNull() else icon_on_w
                mute_btn.setIcon(icon_on_w)
                mute_btn._icon_on = icon_on_w
                mute_btn._icon_off = icon_off_w
            else:
                mute_btn.setText("🔊")
                mute_btn._icon_on = None
        else:
            mute_btn.setText("🔊")
            mute_btn._icon_on = None

        # 초기 음소거 상태
        if is_running:
            initial_muted = audio_control.is_muted(pid) or False
        else:
            initial_muted = getattr(process, 'default_muted', False)
        if initial_muted:
            mute_btn.blockSignals(True)
            mute_btn.setChecked(True)
            mute_btn.blockSignals(False)
            if getattr(mute_btn, '_icon_on', None):
                mute_btn.setIcon(mute_btn._icon_off)
            else:
                mute_btn.setText("🔇")

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)
        slider.setSingleStep(5)
        slider.setPageStep(5)
        slider.setFixedWidth(70)
        slider.setStyleSheet(_SLIDER_STYLE)
        slider.enterEvent = lambda _e: self._reset_auto_hide()  # type: ignore[assignment]

        val_lbl = QLabel()
        val_lbl.setFixedWidth(26)
        val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        val_lbl.setStyleSheet("color: rgba(255,255,255,180); font-size: 11px;")

        vol = getattr(process, 'default_volume', None) or 100
        if is_running:
            actual = audio_control.get_app_volume(pid)
            if actual is not None:
                vol = round((actual * 100) / 5) * 5
        vol = max(0, min(100, vol))
        slider.blockSignals(True)
        slider.setValue(vol)
        slider.blockSignals(False)
        val_lbl.setText(str(vol))

        def on_mute_toggled(checked, p=process, pid_ref=pid, btn=mute_btn):
            if getattr(btn, '_icon_on', None):
                btn.setIcon(btn._icon_off if checked else btn._icon_on)
            else:
                btn.setText("🔇" if checked else "🔊")
            p.default_muted = checked
            self._schedule_volume_save(p)
            if pid_ref is not None:
                audio_control.set_mute(pid_ref, checked)
            self._reset_auto_hide()

        def on_changed(v, p=process, pid_ref=pid, lbl=val_lbl, s=slider):
            snapped = round(v / 5) * 5
            snapped = max(0, min(100, snapped))
            if snapped != v:
                s.blockSignals(True)
                s.setValue(snapped)
                s.blockSignals(False)
            lbl.setText(str(snapped))
            self._on_vol_list_changed(snapped, p, pid_ref)

        mute_btn.toggled.connect(on_mute_toggled)
        slider.valueChanged.connect(on_changed)
        hl.addWidget(mute_btn)
        hl.addWidget(slider)
        hl.addWidget(val_lbl)
        return row

    def _on_vol_list_changed(self, value: int, process: ManagedProcess, pid: Optional[int]) -> None:
        """볼륨 리스트 슬라이더 변경 시 실시간 적용 및 DB 저장 예약."""
        if pid is not None:
            audio_control.set_app_volume(pid, value / 100.0)
        process.default_volume = value
        self._schedule_volume_save(process)
        self._reset_auto_hide()

    def _schedule_volume_save(self, process: ManagedProcess) -> None:
        """500ms 디바운스로 볼륨 DB 저장 예약."""
        existing = self._volume_save_timers.get(process.id)
        if existing is None:
            existing = QTimer(self)
            existing.setSingleShot(True)
            self._volume_save_timers[process.id] = existing
        else:
            existing.stop()
            try:
                existing.timeout.disconnect()
            except TypeError:
                pass

        def _save(p=process):
            class _SaveRunnable(QRunnable):
                def __init__(self, dm, proc):
                    super().__init__()
                    self._dm = dm
                    self._proc = proc
                def run(self):
                    try:
                        self._dm.update_process(self._proc)
                    except Exception:
                        pass
            self._save_pool.start(_SaveRunnable(self._data_manager, p))

        existing.timeout.connect(_save)
        existing.start(500)
