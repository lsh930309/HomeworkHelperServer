"""게임 실행 중 우측에서 슬라이드인하는 사이드바 위젯.

QPropertyAnimation 으로 부드러운 슬라이드 효과를 제공하며,
실행 중인 게임별 클러스터(아이콘/플레이타임/종료버튼)와
전체 볼륨 조절 섹션을 포함합니다.
"""
import logging
import os
import time
from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import (
    Qt, QPropertyAnimation, QEasingCurve, QRect, QTimer,
    QRunnable, QThreadPool, pyqtSlot,
)
from PyQt6.QtGui import QScreen, QColor
from PyQt6.QtWidgets import (
    QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QSizePolicy, QSlider, QVBoxLayout, QWidget,
)

from src.data.data_models import ManagedProcess
from src.utils import audio_control

logger = logging.getLogger(__name__)

# 사이드바 고정 너비 (px)
_SIDEBAR_WIDTH = 280
# 슬라이드 애니메이션 시간 (ms)
_ANIM_DURATION_MS = 220
# 자동 숨김 타이머 기본값 (ms) — SidebarController 가 override 함
_DEFAULT_AUTO_HIDE_MS = 3000

# 스크린샷 썸네일 크기 (px)
_THUMB_W = 76
_THUMB_H = 57
_THUMB_COLS = 3
_THUMB_MAX_CELLS = _THUMB_COLS * 3  # 최대 9셀 (마지막 1셀은 폴더 버튼)


def _tint_icon_white(icon) -> "QIcon":
    """아이콘 픽셀을 흰색으로 틴팅합니다 (다크 배경 전용).

    devicePixelRatio 를 원본에서 그대로 복사해야 HiDPI 환경에서
    논리 픽셀 크기가 보존됩니다.
    """
    from PyQt6.QtGui import QPainter, QColor, QPixmap
    from PyQt6.QtCore import Qt as _Qt
    pixmap = icon.pixmap(16, 16)
    if pixmap.isNull():
        return icon
    result = QPixmap(pixmap.size())
    result.setDevicePixelRatio(pixmap.devicePixelRatio())
    result.fill(_Qt.GlobalColor.transparent)
    painter = QPainter(result)
    painter.drawPixmap(0, 0, pixmap)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(result.rect(), QColor("white"))
    painter.end()
    from PyQt6.QtGui import QIcon
    return QIcon(result)


# 슬라이더 스타일
_SLIDER_STYLE = """
QSlider::groove:horizontal {
    height: 4px;
    background: rgba(255,255,255,28);
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba(100,160,255,200), stop:1 rgba(140,190,255,220));
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: rgba(220,230,255,240);
    border: none;
    width: 12px;
    height: 12px;
    border-radius: 6px;
    margin: -4px 0;
}
QSlider::handle:horizontal:hover {
    background: white;
}
"""

_MUTE_BTN_STYLE = """
QPushButton {
    border: 1px solid rgba(255,255,255,22);
    border-radius: 3px;
    background: rgba(255,255,255,10);
    color: white;
    font-size: 10px;
}
QPushButton:checked {
    background: rgba(80,130,220,160);
    border-color: rgba(100,160,255,180);
    color: white;
}
QPushButton:hover:!checked {
    background: rgba(255,255,255,22);
}
"""


class SidebarWidget(QWidget):
    """게임 오버레이 사이드바 위젯.

    화면 우측에서 슬라이드인하며, 포커스를 빼앗지 않습니다.
    실행 중인 게임마다 클러스터(아이콘·이름, 플레이타임, 게임종료)를 표시하고,
    하단에 전체 등록 게임 볼륨 조절 섹션을 배치합니다.
    """

    def __init__(
        self,
        data_manager,
        auto_hide_ms: int = _DEFAULT_AUTO_HIDE_MS,
        screen: Optional[QScreen] = None,
        reconnect_recording: Optional[Callable[[], None]] = None,
        get_recording_error: Optional[Callable[[], str]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(
            parent,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self._data_manager = data_manager
        self._auto_hide_ms = auto_hide_ms
        self._is_shown = False
        self._reconnect_recording = reconnect_recording
        self._get_recording_error = get_recording_error

        # {process_id: (QLabel, start_timestamp)} — 플레이타임 레이블 트래킹
        self._playtime_labels: dict = {}

        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(_SIDEBAR_WIDTH)

        self._screen = screen or QApplication.primaryScreen()

        # 내부 프레임 (반투명 배경 + 테두리)
        self._frame = QFrame(self)
        self._frame.setObjectName("SidebarFrame")
        self._frame.setStyleSheet("""
            QFrame#SidebarFrame {
                background-color: rgba(12, 12, 16, 240);
                border-left: 1px solid rgba(180, 200, 255, 18);
                border-radius: 0px;
            }
        """)
        frame_layout = QVBoxLayout(self._frame)
        frame_layout.setContentsMargins(12, 16, 12, 12)
        frame_layout.setSpacing(8)

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

        # 현재 시간 갱신 타이머 (1초)
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._update_clock)

        # 커서 위치 폴링 타이머 (200ms) — leaveEvent 오탐 방지
        self._cursor_poll_timer = QTimer(self)
        self._cursor_poll_timer.setInterval(200)
        self._cursor_poll_timer.timeout.connect(self._poll_cursor)

        # 볼륨 저장 전용 직렬 스레드풀
        self._volume_save_timers: dict = {}
        self._save_pool = QThreadPool(self)
        self._save_pool.setMaxThreadCount(1)

        # Win32 외부 클릭 감지 상태
        self._lbutton_was_down: bool = False

        # Win32 블러 효과 (최초 show 후 적용)
        self._blur_applied = False

    # ------------------------------------------------------------------
    # UI 구성
    # ------------------------------------------------------------------

    def _build_ui(self, layout: QVBoxLayout) -> None:
        """사이드바 내부 위젯을 구성합니다."""
        # 메인 스크롤 영역 (세로 스크롤 허용, 가로 스크롤 없음)
        self._main_scroll = QScrollArea()
        self._main_scroll.setWidgetResizable(True)
        self._main_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._main_scroll.setStyleSheet("""
            QScrollArea { border: none; background: transparent; }
            QWidget#scroll_content { background: transparent; }
            QScrollBar:vertical {
                width: 4px; background: transparent; border-radius: 2px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255,255,255,60); border-radius: 2px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
        """)

        self._scroll_content = QWidget()
        self._scroll_content.setObjectName("scroll_content")
        self._scroll_layout = QVBoxLayout(self._scroll_content)
        self._scroll_layout.setContentsMargins(0, 0, 0, 0)
        self._scroll_layout.setSpacing(0)

        # 현재 시간 섹션 (최상단)
        self._clock_widget = QWidget()
        self._clock_widget.setStyleSheet("background: transparent;")
        clock_layout = QVBoxLayout(self._clock_widget)
        clock_layout.setContentsMargins(0, 0, 0, 8)
        clock_layout.setSpacing(2)
        self._clock_label = QLabel()
        self._clock_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._clock_label.setStyleSheet("color: rgba(220,230,255,240); font-size: 28px; font-weight: 300; letter-spacing: 2px; background: transparent;")
        clock_layout.addWidget(self._clock_label)
        self._scroll_layout.insertWidget(0, self._clock_widget)

        # 실행 중 게임 클러스터 영역 (동적으로 채워짐)
        self._active_clusters_layout = QVBoxLayout()
        self._active_clusters_layout.setSpacing(10)
        self._scroll_layout.addLayout(self._active_clusters_layout)

        # 볼륨 섹션 (항상 하단에 고정)
        self._vol_section = QWidget()
        self._vol_section.setStyleSheet("background: transparent;")
        vol_section_layout = QVBoxLayout(self._vol_section)
        vol_section_layout.setContentsMargins(0, 10, 0, 0)
        vol_section_layout.setSpacing(4)

        vol_title = QLabel("볼륨")
        vol_title.setStyleSheet("color: rgba(150,170,210,160); font-size: 10px; letter-spacing: 1px;")
        vol_section_layout.addWidget(vol_title)

        self._vol_list_container = QWidget()
        self._vol_list_container.setStyleSheet("background: transparent;")
        self._vol_list_layout = QVBoxLayout(self._vol_list_container)
        self._vol_list_layout.setContentsMargins(0, 0, 0, 0)
        self._vol_list_layout.setSpacing(4)
        vol_section_layout.addWidget(self._vol_list_container)

        self._scroll_layout.addWidget(self._vol_section)

        # 스크린샷 섹션
        self._screenshot_section = self._build_screenshot_section()
        self._scroll_layout.addWidget(self._screenshot_section)

        # 녹화 섹션
        self._recording_section = self._build_recording_section()
        self._scroll_layout.addWidget(self._recording_section)
        self._scroll_layout.addStretch(1)

        self._main_scroll.setWidget(self._scroll_content)
        layout.addWidget(self._main_scroll, 1)

        # 닫기 버튼 (스크롤 영역 밖, 항상 하단 고정)
        close_btn = QPushButton("닫기")
        close_btn.setFixedHeight(28)
        close_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,10);
                color: rgba(255,255,255,160);
                border: 1px solid rgba(255,255,255,18);
                border-radius: 4px;
                font-size: 11px;
            }
            QPushButton:hover {
                background: rgba(255,255,255,22);
                color: white;
            }
        """)
        close_btn.clicked.connect(self.slide_out)
        layout.addWidget(close_btn)

    # ------------------------------------------------------------------
    # 공개 API
    # ------------------------------------------------------------------

    def update_process(
        self,
        process: Optional[ManagedProcess],
        pid: Optional[int] = None,
        game_start_timestamp: Optional[float] = None,
    ) -> None:
        """(하위 호환) 콘텐츠를 갱신합니다."""
        self.refresh_content()

    def update_auto_hide_ms(self, ms: int) -> None:
        """자동 숨김 대기 시간을 갱신합니다."""
        self._auto_hide_ms = ms

    def refresh_content(self) -> None:
        """게임 클러스터와 볼륨 목록을 모두 갱신합니다."""
        self._update_clock()
        self._refresh_active_sections()
        self._refresh_volumes_list()
        self._refresh_screenshot_section()
        self._refresh_screenshot_thumbnails()
        self._refresh_recording_section()

    def slide_in(self) -> None:
        """사이드바를 화면 우측에서 슬라이드인합니다."""
        if self._is_shown:
            self._reset_auto_hide()
            return

        geo = self._compute_geometry()
        start = QRect(geo.x() + _SIDEBAR_WIDTH, geo.y(), geo.width(), geo.height())
        self.setGeometry(start)
        self.apply_visual_settings()
        self.show()

        if not self._blur_applied:
            self._try_apply_blur()

        self._anim.setStartValue(start)
        self._anim.setEndValue(geo)
        self._anim.start()

        self._is_shown = True
        self.refresh_content()
        self._playtime_timer.start()
        self._clock_timer.start()
        self._cursor_poll_timer.start()
        self._rec_timer.start()
        self._lbutton_was_down = False
        self._reset_auto_hide()
        logger.debug("SidebarWidget 슬라이드인")

    def slide_out(self) -> None:
        """사이드바를 화면 우측으로 슬라이드아웃합니다."""
        if not self._is_shown:
            return

        self._auto_hide_timer.stop()
        self._playtime_timer.stop()
        self._clock_timer.stop()
        self._cursor_poll_timer.stop()
        self._rec_timer.stop()

        geo = self.geometry()
        end = QRect(geo.x() + _SIDEBAR_WIDTH, geo.y(), geo.width(), geo.height())
        self._anim.setStartValue(geo)
        self._anim.setEndValue(end)
        # 중복 연결 방지
        try:
            self._anim.finished.disconnect(self._on_slide_out_finished)
        except (RuntimeError, TypeError):
            pass
        self._anim.finished.connect(self._on_slide_out_finished)
        self._anim.start()

        self._is_shown = False
        logger.debug("SidebarWidget 슬라이드아웃")

    def cleanup(self) -> None:
        """타이머와 애니메이션을 정리합니다."""
        self._auto_hide_timer.stop()
        self._playtime_timer.stop()
        self._clock_timer.stop()
        self._cursor_poll_timer.stop()
        self._anim.stop()
        self.hide()

    # ------------------------------------------------------------------
    # 이벤트 오버라이드
    # ------------------------------------------------------------------

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._frame.setGeometry(0, 0, self.width(), self.height())

    # ------------------------------------------------------------------
    # 내부 메서드 — 레이아웃
    # ------------------------------------------------------------------

    def _refresh_active_sections(self) -> None:
        """실행 중인 게임 클러스터를 재구성합니다."""
        self._playtime_labels.clear()
        while self._active_clusters_layout.count() > 0:
            item = self._active_clusters_layout.takeAt(0)
            if item:
                w = item.widget()
                if w:
                    w.deleteLater()

        active_games = self._get_active_games()
        for process, pid, start_ts in active_games:
            cluster = self._make_game_cluster(process, pid, start_ts)
            self._active_clusters_layout.addWidget(cluster)

    def _get_active_games(self) -> list:
        """실행 중인 게임을 시작 시간 순으로 반환합니다.

        Returns:
            list of (ManagedProcess, pid, start_timestamp)
        """
        from src.gui.main_window import MainWindow
        if not MainWindow.INSTANCE:
            return []
        # dict 복사 - process_monitor 스레드가 동시에 수정할 수 있음
        active = dict(MainWindow.INSTANCE.process_monitor.active_monitored_processes)
        managed = getattr(self._data_manager, 'managed_processes', [])
        managed_map = {p.id: p for p in managed}

        result = []
        for proc_id, entry in active.items():
            process = managed_map.get(proc_id)
            if process:
                pid = entry.get('pid')
                start_ts = entry.get('start_time_approx') or 0.0
                result.append((process, pid, start_ts))
        result.sort(key=lambda x: x[2])
        return result

    def _make_game_cluster(
        self,
        process: ManagedProcess,
        pid: Optional[int],
        start_ts: float,
    ) -> QWidget:
        """단일 실행 게임의 클러스터 위젯을 생성합니다.

        구성: [아이콘 + 이름] / [오늘 플레이타임] / [게임 종료 버튼]
        """
        cluster = QWidget()
        cluster.setStyleSheet(
            "QWidget { background: rgba(255,255,255,5); border: 1px solid rgba(255,255,255,10); border-radius: 8px; }"
        )
        layout = QVBoxLayout(cluster)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(7)

        # ── 헤더: 아이콘 + 이름 ──
        header = QHBoxLayout()
        header.setSpacing(8)

        icon_label = QLabel()
        icon_label.setFixedSize(40, 40)
        icon_label.setStyleSheet(
            "background: rgba(255,255,255,8); border: 1px solid rgba(255,255,255,12); border-radius: 10px;"
        )
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setScaledContents(True)
        header.addWidget(icon_label)

        name_label = QLabel(process.name)
        name_label.setStyleSheet(
            "color: rgba(235,240,255,240); font-weight: 600; font-size: 13px; background: transparent;"
        )
        name_label.setWordWrap(True)
        header.addWidget(name_label, 1)
        layout.addLayout(header)

        # 아이콘 비동기 로드
        self._load_icon_async(process, icon_label)

        # ── 플레이타임 ──
        gs = getattr(self._data_manager, 'global_settings', None)
        playtime_enabled = getattr(gs, 'sidebar_playtime_enabled', True) if gs else True
        playtime_prefix = getattr(gs, 'sidebar_playtime_prefix', '오늘 플레이 시간') if gs else '오늘 플레이 시간'
        playtime_label = QLabel("0분")
        playtime_label.setStyleSheet(
            "color: rgba(160,180,220,200); font-size: 11px; background: transparent;"
        )
        playtime_label.setVisible(playtime_enabled)
        layout.addWidget(playtime_label)
        self._playtime_labels[process.id] = (playtime_label, start_ts, playtime_prefix)
        self._update_playtime_label(playtime_label, start_ts, playtime_prefix)

        # ── 게임 종료 버튼 ──
        kill_btn = QPushButton("게임 종료")
        kill_btn.setFixedHeight(28)
        kill_btn.setStyleSheet("""
            QPushButton {
                background: rgba(160, 30, 30, 160);
                color: rgba(255,200,200,220);
                border: 1px solid rgba(200, 60, 60, 120);
                border-radius: 5px;
                font-size: 11px;
            }
            QPushButton:hover  { background: rgba(200, 40, 40, 200); color: white; }
            QPushButton:pressed { background: rgba(130, 20, 20, 220); }
        """)
        kill_btn.clicked.connect(lambda _=False, p=pid: self._kill_process(p))
        layout.addWidget(kill_btn)

        return cluster

    def _kill_process(self, pid: Optional[int]) -> None:
        """프로세스를 백그라운드 스레드에서 종료합니다."""
        if pid is None:
            return

        class _KillRunnable(QRunnable):
            def __init__(self, target_pid: int):
                super().__init__()
                self._pid = target_pid

            def run(self):
                try:
                    import psutil
                    psutil.Process(self._pid).terminate()
                except Exception:
                    pass

        QThreadPool.globalInstance().start(_KillRunnable(pid))
        self.slide_out()

    # ------------------------------------------------------------------
    # 내부 메서드 — 플레이타임
    # ------------------------------------------------------------------

    def _update_playtime_label(self, label: QLabel, start_ts: float, prefix: str = "오늘 플레이 시간") -> None:
        """경과 시간을 계산해 레이블 텍스트를 갱신합니다."""
        if not start_ts:
            label.setText(f"{prefix}: 0분")
            return
        elapsed = int(time.time() - start_ts)
        h = elapsed // 3600
        m = (elapsed % 3600) // 60
        if h > 0:
            elapsed_text = f"{h}시간 {m:02d}분"
        else:
            elapsed_text = f"{m}분"
        label.setText(f"{prefix}: {elapsed_text}")

    def _refresh_playtime(self) -> None:
        """1초 타이머마다 모든 실행 중 게임의 플레이타임 레이블을 갱신합니다."""
        for entry in self._playtime_labels.values():
            label, start_ts, prefix = entry
            self._update_playtime_label(label, start_ts, prefix)

    def _update_clock(self) -> None:
        """현재 시간 레이블을 갱신합니다."""
        import datetime
        gs = getattr(self._data_manager, 'global_settings', None)
        fmt = getattr(gs, 'sidebar_clock_format', '%H:%M:%S') if gs else '%H:%M:%S'
        self._clock_label.setText(datetime.datetime.now().strftime(fmt))
        enabled = getattr(gs, 'sidebar_clock_enabled', True) if gs else True
        self._clock_widget.setVisible(enabled)

    # ------------------------------------------------------------------
    # 내부 메서드 — 아이콘 비동기 로드
    # ------------------------------------------------------------------

    def _load_icon_async(self, process: ManagedProcess, icon_label: QLabel) -> None:
        """게임 아이콘을 백그라운드 스레드에서 추출해 icon_label 에 반영합니다."""
        from PyQt6.QtCore import QThread, pyqtSignal as Signal

        class _IconLoader(QThread):
            icon_loaded = Signal(object)

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
                    logger.debug("아이콘 로드 실패: %s", self._path, exc_info=True)

        loader = _IconLoader(process.monitoring_path, self)

        def _on_icon(pixmap, lbl=icon_label):
            try:
                if not pixmap.isNull():
                    lbl.setPixmap(pixmap)
            except RuntimeError:
                pass  # icon_label 이 이미 삭제된 경우 무시
            loader.deleteLater()

        loader.icon_loaded.connect(_on_icon)
        loader.start()

    # ------------------------------------------------------------------
    # 내부 메서드 — 볼륨 섹션
    # ------------------------------------------------------------------

    def _refresh_volumes_list(self) -> None:
        """모든 등록 게임에 대한 볼륨 행을 재구성합니다."""
        gs = getattr(self._data_manager, 'global_settings', None)
        vol_enabled = getattr(gs, 'sidebar_volume_section_enabled', True) if gs else True
        self._vol_section.setVisible(vol_enabled)

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

        from src.gui.main_window import MainWindow
        active_pids: dict = {}
        if MainWindow.INSTANCE:
            # dict 복사 - process_monitor 스레드가 동시에 수정할 수 있음
            active_snapshot = dict(MainWindow.INSTANCE.process_monitor.active_monitored_processes)
            active_pids = {
                proc_id: entry.get('pid')
                for proc_id, entry in active_snapshot.items()
            }

        for proc in processes:
            self._vol_list_layout.addWidget(
                self._make_vol_row(proc, active_pids.get(proc.id))
            )

    def _make_vol_row(self, process: ManagedProcess, pid: Optional[int]) -> QWidget:
        """다크 테마 볼륨 행 (녹색 점 + 이름 + 음소거 버튼 + 슬라이더 + 값 레이블)."""
        is_running = pid is not None
        row = QWidget()
        row.setStyleSheet("background: transparent; border-radius: 4px;")
        hl = QHBoxLayout(row)
        hl.setContentsMargins(4, 2, 4, 2)
        hl.setSpacing(4)

        dot_lbl = QLabel("●")
        dot_lbl.setFixedWidth(10)
        dot_lbl.setStyleSheet(
            "color: rgba(80,200,120,220); font-size: 7px;" if is_running
            else "color: transparent; font-size: 7px;"
        )
        hl.addWidget(dot_lbl)

        name_lbl = QLabel(process.name)
        name_lbl.setStyleSheet("color: rgba(200,210,235,200); font-size: 11px;")
        name_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        hl.addWidget(name_lbl, 1)

        mute_btn = QPushButton()
        mute_btn.setFixedSize(22, 22)
        mute_btn.setCheckable(True)
        mute_btn.setStyleSheet(_MUTE_BTN_STYLE)

        from PyQt6.QtWidgets import QStyle
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

        if is_running:
            try:
                initial_muted = audio_control.is_muted(pid) or False
            except Exception:
                initial_muted = getattr(process, 'default_muted', False)
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
        slider.setFixedWidth(80)
        slider.setStyleSheet(_SLIDER_STYLE)
        slider.enterEvent = lambda _e: self._reset_auto_hide()  # type: ignore[assignment]

        val_lbl = QLabel()
        val_lbl.setFixedWidth(28)
        val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        val_lbl.setStyleSheet("color: rgba(160,180,220,180); font-size: 11px;")

        vol = getattr(process, 'default_volume', None) or 100
        if is_running:
            try:
                actual = audio_control.get_app_volume(pid)
                if actual is not None:
                    vol = round((actual * 100) / 5) * 5
            except Exception:
                pass
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
                        logger.exception("볼륨 저장 실패: %s", self._proc.name)

            self._save_pool.start(_SaveRunnable(self._data_manager, p))

        existing.timeout.connect(_save)
        existing.start(500)

    # ------------------------------------------------------------------
    # 내부 메서드 — 타이머 / 애니메이션 / 효과
    # ------------------------------------------------------------------

    def _compute_geometry(self) -> QRect:
        screen = self._screen or QApplication.primaryScreen()
        if screen is None:
            return QRect(0, 0, _SIDEBAR_WIDTH, 600)
        geo = screen.geometry()
        gs = getattr(self._data_manager, 'global_settings', None)
        height_ratio = max(0.3, min(1.0, getattr(gs, 'sidebar_height_ratio', 1.0) if gs else 1.0))
        sidebar_height = int(geo.height() * height_ratio)
        y_offset = (geo.height() - sidebar_height) // 2
        x = geo.right() - _SIDEBAR_WIDTH + 1
        return QRect(x, geo.top() + y_offset, _SIDEBAR_WIDTH, sidebar_height)

    def update_screen(self, screen: Optional[QScreen]) -> None:
        """화면 변경 시 스크린 참조를 갱신하고 geometry를 재계산합니다."""
        self._screen = screen
        if self._is_shown:
            geo = self._compute_geometry()
            self.setGeometry(geo)
        logger.debug("SidebarWidget 스크린 갱신: %s", screen.name() if screen else "None")

    def apply_visual_settings(self) -> None:
        """투명도·geometry 설정을 즉시 반영합니다."""
        gs = getattr(self._data_manager, 'global_settings', None)
        opacity = max(0.1, min(1.0, getattr(gs, 'sidebar_opacity', 0.85) if gs else 0.85))
        self.setWindowOpacity(opacity)
        if self._is_shown:
            geo = self._compute_geometry()
            self.setGeometry(geo)

    def _reset_auto_hide(self) -> None:
        if self._auto_hide_ms > 0:
            self._auto_hide_timer.start(self._auto_hide_ms)

    def _poll_cursor(self) -> None:
        from PyQt6.QtGui import QCursor
        cursor_pos = QCursor.pos()
        inside = self.rect().contains(self.mapFromGlobal(cursor_pos))

        # 자동 숨김 타이머 관리
        if inside:
            if self._auto_hide_timer.isActive():
                self._auto_hide_timer.stop()
        else:
            if self._auto_hide_ms == 0:
                self.slide_out()
                return
            elif not self._auto_hide_timer.isActive():
                self._reset_auto_hide()

        # Win32 좌클릭 감지 (전체화면 게임 포함)
        try:
            import ctypes
            state = ctypes.windll.user32.GetAsyncKeyState(0x01)
            lbutton_down = bool(state & 0x8000)
        except Exception:
            lbutton_down = False

        if lbutton_down and not self._lbutton_was_down:
            # 새 클릭 감지 — 사이드바 영역 밖이면 숨김
            if not inside:
                self._lbutton_was_down = True
                self.slide_out()
                return
        self._lbutton_was_down = lbutton_down

    # ------------------------------------------------------------------
    # 내부 메서드 — 스크린샷 섹션
    # ------------------------------------------------------------------

    def _build_screenshot_section(self) -> QWidget:
        """스크린샷 섹션 위젯을 구성합니다."""
        section = QWidget()
        section.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(4)

        # 헤더 행
        header = QHBoxLayout()
        title = QLabel("스크린샷")
        title.setStyleSheet(
            "color: rgba(150,170,210,160); font-size: 10px; letter-spacing: 1px;"
        )
        self._capture_now_btn = QPushButton("지금 촬영")
        self._capture_now_btn.setFixedHeight(28)
        self._capture_now_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,10);
                color: rgba(255,255,255,160);
                border: 1px solid rgba(255,255,255,18);
                border-radius: 4px;
                font-size: 11px;
            }
            QPushButton:hover { background: rgba(255,255,255,22); color: white; }
        """)
        self._capture_now_btn.clicked.connect(self._on_capture_now_clicked)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self._capture_now_btn)
        layout.addLayout(header)

        # 썸네일 그리드
        self._thumb_grid_container = QWidget()
        self._thumb_grid_container.setStyleSheet("background: transparent;")
        self._thumb_grid_layout = QGridLayout(self._thumb_grid_container)
        self._thumb_grid_layout.setSpacing(3)
        self._thumb_grid_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._thumb_grid_container)

        return section

    def _build_recording_section(self) -> QWidget:
        """녹화 상태 섹션 위젯을 구성합니다."""
        section = QWidget()
        section.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(4)

        title = QLabel("녹화")
        title.setStyleSheet(
            "color: rgba(150,170,210,160); font-size: 10px; letter-spacing: 1px;"
        )
        layout.addWidget(title)

        self._rec_status_label = QLabel("○ OBS 오프라인")
        self._rec_status_label.setStyleSheet("color: #888; font-size: 12px;")
        layout.addWidget(self._rec_status_label)

        self._rec_stop_btn = QPushButton("■ 녹화 종료")
        self._rec_stop_btn.setFixedHeight(28)
        self._rec_stop_btn.setStyleSheet("""
            QPushButton {
                background: rgba(160, 30, 30, 160);
                color: rgba(255,200,200,220);
                border: 1px solid rgba(200, 60, 60, 120);
                border-radius: 5px;
                font-size: 11px;
            }
            QPushButton:hover { background: rgba(200, 40, 40, 200); color: white; }
            QPushButton:pressed { background: rgba(130, 20, 20, 220); }
        """)
        self._rec_stop_btn.clicked.connect(self._on_rec_stop_clicked)
        self._rec_stop_btn.hide()
        layout.addWidget(self._rec_stop_btn)

        # OBS 재연결 버튼 (obs_offline 상태에서만 표시)
        self._rec_connect_btn = QPushButton("↺ OBS 재연결")
        self._rec_connect_btn.setFixedHeight(26)
        self._rec_connect_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,12);
                color: rgba(180,200,240,200);
                border: 1px solid rgba(255,255,255,25);
                border-radius: 5px;
                font-size: 11px;
            }
            QPushButton:hover { background: rgba(255,255,255,22); color: white; }
            QPushButton:pressed { background: rgba(255,255,255,8); }
        """)
        self._rec_connect_btn.clicked.connect(self._on_rec_connect_clicked)
        layout.addWidget(self._rec_connect_btn)

        # 녹화 상태
        self._rec_state = "obs_offline"
        self._rec_elapsed_sec = 0
        self._stop_recording_callback = None

        # 녹화 타이머 (1초)
        self._rec_timer = QTimer(self)
        self._rec_timer.setInterval(1000)
        self._rec_timer.timeout.connect(self._update_rec_timer)

        return section

    def set_on_stop_recording(self, fn) -> None:
        """녹화 종료 버튼 클릭 시 호출될 콜백을 등록합니다."""
        self._stop_recording_callback = fn

    def set_on_reconnect_recording(self, fn: Optional[Callable[[], None]]) -> None:
        """녹화 재연결 버튼 클릭 시 호출될 콜백을 등록합니다."""
        self._reconnect_recording = fn

    def set_recording_error_provider(self, fn: Optional[Callable[[], str]]) -> None:
        """최근 녹화 연결 오류 메시지를 제공하는 콜백을 등록합니다."""
        self._get_recording_error = fn

    def on_recording_state_changed(self, state: str) -> None:
        """MainWindow에서 호출하는 슬롯. state: 'idle'|'recording'|'connecting'|'obs_offline'"""
        self._rec_state = state
        if state == "recording":
            self._rec_elapsed_sec = 0
        self._update_rec_ui()

    def _update_rec_ui(self) -> None:
        state = getattr(self, '_rec_state', 'obs_offline')
        elapsed = getattr(self, '_rec_elapsed_sec', 0)
        if state == "recording":
            mins, secs = divmod(elapsed, 60)
            hrs, mins = divmod(mins, 60)
            self._rec_status_label.setText(f"● REC  {hrs:02d}:{mins:02d}:{secs:02d}")
            self._rec_status_label.setStyleSheet("color: #e05555; font-size: 12px;")
            self._rec_stop_btn.show()
            self._rec_connect_btn.hide()
        elif state == "idle":
            self._rec_status_label.setText("● OBS 대기 중")
            self._rec_status_label.setStyleSheet("color: #5aaa5a; font-size: 12px;")
            self._rec_stop_btn.hide()
            self._rec_connect_btn.hide()
        elif state == "connecting":
            self._rec_status_label.setText("○ OBS 연결 중...")
            self._rec_status_label.setStyleSheet("color: #aaa850; font-size: 12px;")
            self._rec_stop_btn.hide()
            self._rec_connect_btn.hide()
        else:  # obs_offline
            self._rec_status_label.setText("○ OBS 오프라인")
            self._rec_status_label.setStyleSheet("color: #888; font-size: 12px;")
            self._rec_stop_btn.hide()
            self._rec_connect_btn.show()
            # 마지막 연결 실패 이유를 툴팁으로 표시
            err = self._get_recording_error() if self._get_recording_error else ""
            self._rec_status_label.setToolTip(err if err else "")
            self._rec_connect_btn.setToolTip(err if err else "")

    def _update_rec_timer(self) -> None:
        """1초 tick. recording 상태일 때만 elapsed 증가."""
        if getattr(self, '_rec_state', '') == "recording":
            self._rec_elapsed_sec = getattr(self, '_rec_elapsed_sec', 0) + 1
            self._update_rec_ui()

    def _on_rec_stop_clicked(self) -> None:
        if self._stop_recording_callback:
            self._stop_recording_callback()

    def _on_rec_connect_clicked(self) -> None:
        """OBS 재연결 버튼 클릭 — 연결만 시도하고 녹화는 시작하지 않는다."""
        if self._reconnect_recording:
            self._reconnect_recording()

    def _refresh_recording_section(self) -> None:
        """recording_enabled 설정에 따라 섹션 show/hide."""
        gs = getattr(self._data_manager, 'global_settings', None)
        enabled = getattr(gs, 'recording_enabled', False) if gs else False
        self._recording_section.setVisible(enabled)

    def _refresh_screenshot_section(self) -> None:
        """스크린샷 섹션 표시 여부를 설정에 따라 갱신합니다."""
        gs = getattr(self._data_manager, 'global_settings', None)
        enabled = getattr(gs, 'screenshot_enabled', True) if gs else True
        self._screenshot_section.setVisible(enabled)
        # 캡처 버튼 활성화 여부 (ScreenshotManager 참조는 MainWindow에 있으므로 항상 활성)
        self._capture_now_btn.setEnabled(True)

    @pyqtSlot()
    def _refresh_screenshot_thumbnails(self) -> None:
        """스크린샷 썸네일 그리드를 최신 파일로 갱신합니다."""
        # 그리드 초기화
        while self._thumb_grid_layout.count():
            item = self._thumb_grid_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        gs = getattr(self._data_manager, 'global_settings', None)
        enabled = getattr(gs, 'screenshot_enabled', True) if gs else True
        if not enabled:
            return

        save_dir_str = getattr(gs, 'screenshot_save_dir', '') if gs else ''
        if not save_dir_str:
            from src.screenshot.capture import _DEFAULT_SAVE_DIR
            save_dir_str = str(_DEFAULT_SAVE_DIR)

        from pathlib import Path
        save_path = Path(save_dir_str)
        if not save_path.exists():
            return

        # 최신 파일 목록 (png + jpg + bmp)
        files = sorted(
            [f for f in save_path.iterdir()
             if f.suffix.lower() in ('.png', '.jpg', '.jpeg', '.bmp') and f.is_file()],
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )

        max_shown = _THUMB_MAX_CELLS - 1  # 마지막 셀 = 폴더 버튼
        shown = files[:max_shown]
        remaining = max(0, len(files) - max_shown)

        # 썸네일 셀 추가
        for idx, fp in enumerate(shown):
            row, col = divmod(idx, _THUMB_COLS)
            cell = self._make_thumb_cell(fp)
            self._thumb_grid_layout.addWidget(cell, row, col)

        # 폴더 버튼 (마지막 셀)
        folder_label = f"+{remaining}" if remaining > 0 else "\U0001F4C2"
        folder_btn = QPushButton(folder_label)
        folder_btn.setFixedSize(_THUMB_W, _THUMB_H)
        folder_btn.setToolTip("스크린샷 폴더 열기")
        folder_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,8);
                color: rgba(180,200,240,200);
                border: 1px dashed rgba(255,255,255,25);
                border-radius: 3px;
                font-size: 11px;
            }
            QPushButton:hover { background: rgba(255,255,255,18); color: white; }
        """)
        _dir = save_dir_str

        def _open_folder(d: str = _dir) -> None:
            if Path(d).exists():
                os.startfile(d)
                return
            logger.warning("스크린샷 폴더가 존재하지 않습니다: %s", d)

        folder_btn.clicked.connect(lambda _checked=False: _open_folder())
        next_idx = len(shown)
        row, col = divmod(next_idx, _THUMB_COLS)
        self._thumb_grid_layout.addWidget(folder_btn, row, col)

    def _make_thumb_cell(self, filepath) -> QPushButton:
        """썸네일 셀 QPushButton을 반환합니다."""
        from PyQt6.QtGui import QPixmap, QIcon
        from PyQt6.QtCore import Qt as _Qt
        btn = QPushButton()
        btn.setFixedSize(_THUMB_W, _THUMB_H)
        btn.setToolTip(str(filepath.name))
        btn.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,6);
                border: 1px solid rgba(255,255,255,15);
                border-radius: 3px;
                padding: 0;
            }
            QPushButton:hover { border-color: rgba(100,160,255,180); }
        """)
        # 썸네일 로드 (동기, 작은 파일이므로 허용)
        try:
            pixmap = QPixmap(str(filepath))
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    _THUMB_W, _THUMB_H,
                    _Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    _Qt.TransformationMode.SmoothTransformation,
                )
                x_off = (scaled.width() - _THUMB_W) // 2
                y_off = (scaled.height() - _THUMB_H) // 2
                cropped = scaled.copy(x_off, y_off, _THUMB_W, _THUMB_H)
                btn.setIcon(QIcon(cropped))
                btn.setIconSize(cropped.size())
        except Exception:
            logger.exception("썸네일 로드 실패: %s", filepath)
        _fp = filepath
        btn.clicked.connect(
            lambda _checked=False, p=_fp: __import__('os').startfile(str(p))
        )
        return btn

    def _on_capture_now_clicked(self) -> None:
        """'지금 촬영' 버튼 클릭 핸들러."""
        from src.gui.main_window import MainWindow
        if MainWindow.INSTANCE and hasattr(MainWindow.INSTANCE, '_screenshot_manager'):
            mgr = MainWindow.INSTANCE._screenshot_manager
            if mgr:
                self.hide()

                def _capture() -> None:
                    path = mgr.capture_now()
                    self.show()
                    if path:
                        self._refresh_screenshot_thumbnails()
                    self._reset_auto_hide()

                QTimer.singleShot(100, _capture)

    def on_screenshot_captured(self, path: str) -> None:
        """외부(MainWindow)에서 캡처 완료 시 호출됩니다. 워커 스레드에서 호출 가능."""
        from PyQt6.QtCore import QMetaObject, Qt
        QMetaObject.invokeMethod(
            self, "_refresh_screenshot_thumbnails",
            Qt.ConnectionType.QueuedConnection,
        )

    def _on_slide_out_finished(self) -> None:
        try:
            self._anim.finished.disconnect(self._on_slide_out_finished)
        except (RuntimeError, TypeError):
            pass
        self.hide()

    def _try_apply_blur(self) -> None:
        try:
            from src.gui.sidebar.win32_effects import apply_blur_effect
            hwnd = int(self.winId())
            effect = "acrylic"
            if self._data_manager and hasattr(self._data_manager, 'global_settings'):
                effect = getattr(self._data_manager.global_settings, 'sidebar_effect', 'acrylic')
            self._blur_applied = apply_blur_effect(hwnd, effect)
        except Exception:
            logger.debug("사이드바 블러 효과 적용 실패", exc_info=True)
