"""등록 게임·음량과 하단 미디어 갤러리를 하나로 보여주는 Acrylic 사이드바."""
import logging
import os
import time
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import (
    Qt, QObject, QPropertyAnimation, QEasingCurve, QSize,
    QEvent, QRect, QTimer, QRunnable, QThreadPool, QSignalBlocker, Signal, Slot,
)
from PySide6.QtGui import QScreen, QColor, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QLayout, QPushButton, QScrollArea, QSizePolicy, QStyle, QTabBar, QVBoxLayout, QWidget,
)

from src.data.data_models import ManagedProcess
from src.core.process_monitor import terminate_managed_process
from src.core.launcher import Launcher
from src.core.launch_target import resolve_launch_args
from src.utils import audio_control
from src.utils.windows import get_visible_taskbar_work_area, focus_managed_process_window
from src.gui.sidebar.controls import SidebarClockFace, SidebarDivider, VolumeDial
from src.gui.sidebar.media_panel import MediaCenterPanel
from src.gui.sidebar.win32_effects import ACRYLIC_TINT
from src.gui.work_coordinator import retain_detached_qthreadpool
from src.utils.clipboard import copy_file_to_clipboard
from src.gui.widgets_style import GameIconLabel, apply_sidebar_widgets_style

logger = logging.getLogger(__name__)

# 사이드바 고정 너비 (px)
_SIDEBAR_WIDTH = 280
# 슬라이드 애니메이션 시간 (ms)
_ANIM_DURATION_MS = 220
# 자동 숨김 타이머 기본값 (ms) — SidebarController 가 override 함
_DEFAULT_AUTO_HIDE_MS = 3000

# 갤러리 셀은 가용 너비에서 계산한다. 디코딩 해상도는 배치 치수와 독립이다.
_THUMB_COLS = 3
_THUMB_MAX_ROWS = 2

# 고화질 썸네일 로드 크기 (hover 확대 시 선명도 확보)
_THUMB_HIRES_W = 152
_THUMB_HIRES_H = 114


class _ThumbnailLoadSignals(QObject):
    loaded = Signal(int, str, object)


class _ProcessStopSignals(QObject):
    completed = Signal()


class _ProcessLaunchTask(QRunnable):
    """화면에서 확정한 실행 정책을 소비하며 운영 앱 종료 후 대기 실행을 취소한다."""

    def __init__(self, process_id, target, mode, args, run_as_admin, shutdown_event):
        super().__init__()
        self._process_id, self._target, self._mode = process_id, target, mode
        self._args, self._run_as_admin = args, run_as_admin
        self._shutdown_event = shutdown_event

    def run(self) -> None:
        launcher = Launcher(run_as_admin=self._run_as_admin)
        com = None
        try:
            if os.name == "nt":
                import pythoncom
                pythoncom.CoInitialize()
                com = pythoncom
            accepted = launcher.launch_process(
                self._target, args=self._args, managed_process_id=self._process_id,
                launch_mode=self._mode, cancelled=self._shutdown_event.is_set,
            )
            log = logger.info if accepted else logger.warning
            log("사이드바 게임 실행 요청: 등록=%s 모드=%s 수락=%s 결과=%s",
                self._process_id, self._mode, accepted, launcher.last_error or "실행 요청 수락")
        except Exception:
            logger.exception("사이드바 게임 실행 요청 실패: 등록=%s", self._process_id)
        finally:
            if com is not None:
                com.CoUninitialize()


class _IconLoadSignals(QObject):
    loaded = Signal(str, str, object)


class _IconLoadTask(QRunnable):
    """기존 아이콘 캐시를 공유하고 작업 스레드에는 QImage만 생성한다."""

    def __init__(self, process_id: str, path: str, signals: _IconLoadSignals):
        super().__init__()
        self._process_id, self._path, self._signals = process_id, path, signals

    def run(self) -> None:
        image = None
        com = None
        try:
            if os.name == "nt":
                import pythoncom
                pythoncom.CoInitialize()
                com = pythoncom
            from src.api.dashboard.icons import get_icon_for_size, extract_icon_from_exe, safe_icon_cache_key
            key = safe_icon_cache_key(self._process_id)
            path = get_icon_for_size(key, 48)
            if path is None and os.path.isfile(self._path):
                extract_icon_from_exe(self._path, key)
                path = get_icon_for_size(key, 48)
            if path is not None:
                candidate = QImage(str(path))
                if not candidate.isNull():
                    image = candidate
        except Exception:
            logger.debug("게임 아이콘 로드 실패: %s", self._path, exc_info=True)
        finally:
            if com is not None:
                com.CoUninitialize()
        self._signals.loaded.emit(self._process_id, self._path, image)


class _ProcessStopTask(QRunnable):
    """GUI에서 확정한 등록 대상과 OS identity만 사용하는 종료 작업."""

    def __init__(self, process: ManagedProcess, pid: int, create_time: float,
                 run_as_admin: bool, signals: _ProcessStopSignals):
        super().__init__()
        self._process = process
        self._pid = pid
        self._create_time = create_time
        self._run_as_admin = run_as_admin
        self._signals = signals

    def run(self) -> None:
        try:
            result = terminate_managed_process(
                self._process,
                run_as_admin=self._run_as_admin,
                pid=self._pid,
                create_time=self._create_time,
            )
        except Exception as exc:
            result = {"accepted": False, "status": "failed", "message": str(exc)}
        log = logger.info if result.get("accepted") else logger.warning
        log("사이드바 게임 종료 요청: 이름=%s 등록=%s PID=%s 상태=%s 결과=%s",
            self._process.name, self._process.id, self._pid,
            result.get("status", "unknown"), result.get("message", ""))
        self._signals.completed.emit()


class _ThumbnailLoadTask(QRunnable):
    """이미지 파일(PNG/JPG) 고화질 썸네일 비동기 로드 태스크."""

    def __init__(self, request_id: int, path: str, signals: _ThumbnailLoadSignals):
        super().__init__()
        self._request_id = request_id
        self._path = path
        self._signals = signals

    @staticmethod
    def _build_thumbnail(path: str) -> Optional[QImage]:
        image = QImage(path)
        if image.isNull():
            return None
        # 2배 해상도로 로드 — hover 확대 시 선명도 확보
        scaled = image.scaled(
            _THUMB_HIRES_W,
            _THUMB_HIRES_H,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        x_off = max(0, (scaled.width() - _THUMB_HIRES_W) // 2)
        y_off = max(0, (scaled.height() - _THUMB_HIRES_H) // 2)
        return scaled.copy(x_off, y_off, _THUMB_HIRES_W, _THUMB_HIRES_H)

    def run(self) -> None:
        try:
            image = self._build_thumbnail(self._path)
        except Exception:
            logger.exception("썸네일 로드 실패: %s", self._path)
            image = None
        self._signals.loaded.emit(self._request_id, self._path, image)


class _VideoThumbnailLoadTask(QRunnable):
    """MP4 비디오 썸네일 비동기 로드 태스크 (Windows Shell API 사용)."""

    def __init__(self, request_id: int, path: str, signals: _ThumbnailLoadSignals) -> None:
        super().__init__()
        self._request_id = request_id
        self._path = path
        self._signals = signals

    @staticmethod
    def _extract_thumbnail(path: str, w: int, h: int) -> Optional[QImage]:
        """Windows IShellItemImageFactory로 비디오 썸네일을 추출합니다."""
        co_initialized = False
        psi = None
        psiif = None
        hbm = None
        hdc = None
        release_si = None
        release_siif = None
        ole32 = None
        gdi32 = None
        user32 = None
        try:
            import ctypes
            import ctypes.wintypes as wintypes
            from ctypes import POINTER, byref, c_int, c_uint, c_void_p, c_wchar_p

            shell32 = ctypes.windll.shell32
            ole32 = ctypes.windll.ole32
            gdi32 = ctypes.windll.gdi32
            user32 = ctypes.windll.user32

            # S_OK(0)와 S_FALSE(1)는 모두 이 스레드가 대응하는
            # CoUninitialize()를 호출해야 하는 성공 결과다.
            co_hr = int(ole32.CoInitializeEx(None, 0))  # COINIT_APARTMENTTHREADED
            if co_hr not in (0, 1):
                return None
            co_initialized = True

            def _make_guid(s: str):
                import uuid
                b = uuid.UUID(s).bytes_le
                return (ctypes.c_byte * 16)(*b)

            IID_IShellItem = _make_guid("43826D1E-E718-42EE-BC55-A1E261C37BFE")
            IID_ISIIF = _make_guid("BCC18B79-BA16-442F-80C4-8A59C30C463B")

            psi = c_void_p()
            hr = shell32.SHCreateItemFromParsingName(
                c_wchar_p(path), None,
                byref(IID_IShellItem), byref(psi),
            )
            if hr != 0 or not psi:
                return None

            vtbl = ctypes.cast(psi, POINTER(POINTER(c_void_p)))
            QI_fn = ctypes.WINFUNCTYPE(c_int, c_void_p, POINTER(ctypes.c_byte * 16), POINTER(c_void_p))(vtbl[0][0])
            release_si = ctypes.WINFUNCTYPE(c_uint, c_void_p)(vtbl[0][2])

            psiif = c_void_p()
            hr = QI_fn(psi, byref(IID_ISIIF), byref(psiif))

            if hr != 0 or not psiif:
                return None

            class _SIZE(ctypes.Structure):
                _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]

            vtbl2 = ctypes.cast(psiif, POINTER(POINTER(c_void_p)))
            GetImage_fn = ctypes.WINFUNCTYPE(c_int, c_void_p, _SIZE, c_uint, POINTER(wintypes.HBITMAP))(vtbl2[0][3])
            release_siif = ctypes.WINFUNCTYPE(c_uint, c_void_p)(vtbl2[0][2])

            SIIGBF_BIGGERSIZEOK = 0x1
            hbm = wintypes.HBITMAP()
            hr = GetImage_fn(psiif, _SIZE(w, h), SIIGBF_BIGGERSIZEOK, byref(hbm))

            if hr != 0 or not hbm:
                return None

            class _BITMAPINFOHEADER(ctypes.Structure):
                _fields_ = [
                    ("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                    ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                    ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                    ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                    ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                    ("biClrImportant", ctypes.c_uint32),
                ]

            hdc = user32.GetDC(0)
            if not hdc:
                return None
            bih = _BITMAPINFOHEADER()
            bih.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
            bih.biWidth = w
            bih.biHeight = -h  # top-down DIB
            bih.biPlanes = 1
            bih.biBitCount = 32
            bih.biCompression = 0  # BI_RGB

            buf = ctypes.create_string_buffer(w * h * 4)
            copied_rows = gdi32.GetDIBits(hdc, hbm, 0, h, buf, byref(bih), 0)
            if copied_rows != h:
                return None

            img = QImage(buf, w, h, w * 4, QImage.Format.Format_ARGB32)
            return img.copy()  # buf GC 전에 복사

        except Exception as exc:
            logger.debug("비디오 썸네일 추출 실패 (%s): %s", path, exc)
            return None
        finally:
            cleanup_calls = (
                ("DC", user32.ReleaseDC, (0, hdc)) if hdc and user32 is not None else None,
                ("HBITMAP", gdi32.DeleteObject, (hbm,)) if hbm and gdi32 is not None else None,
                ("IShellItemImageFactory", release_siif, (psiif,)) if psiif and release_siif is not None else None,
                ("IShellItem", release_si, (psi,)) if psi and release_si is not None else None,
                ("COM", ole32.CoUninitialize, ()) if co_initialized and ole32 is not None else None,
            )
            for cleanup in cleanup_calls:
                if cleanup is None:
                    continue
                label, function, args = cleanup
                try:
                    function(*args)
                except Exception:
                    logger.debug("비디오 썸네일 %s 해제 실패", label, exc_info=True)

    @staticmethod
    def _make_placeholder(w: int, h: int) -> QImage:
        """썸네일 추출 실패 시 회색 플레이 아이콘 플레이스홀더."""
        from PySide6.QtGui import QPainter, QPainterPath
        img = QImage(w, h, QImage.Format.Format_ARGB32)
        img.fill(QColor(40, 40, 50, 255))
        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        size = min(w, h) * 0.35
        cx, cy = w / 2, h / 2
        path = QPainterPath()
        path.moveTo(cx - size * 0.4, cy - size * 0.5)
        path.lineTo(cx + size * 0.6, cy)
        path.lineTo(cx - size * 0.4, cy + size * 0.5)
        path.closeSubpath()
        painter.fillPath(path, QColor(160, 160, 180, 200))
        painter.end()
        return img

    def run(self) -> None:
        image = self._extract_thumbnail(self._path, _THUMB_HIRES_W, _THUMB_HIRES_H)
        if image is None:
            image = self._make_placeholder(_THUMB_HIRES_W, _THUMB_HIRES_H)
        self._signals.loaded.emit(self._request_id, self._path, image)


class _HoverThumbCell(QLabel):
    """썸네일 셀. 마우스 오버 시 흰색 테두리를 표시한다."""

    _STYLE_NORMAL = (
        "QLabel { background: rgba(255,255,255,6);"
        " border: none; border-radius: 3px; }"
    )
    _STYLE_HOVER = (
        "QLabel { background: rgba(255,255,255,10);"
        " border: 2px solid rgba(255,255,255,200); border-radius: 3px; }"
    )

    def __init__(
        self,
        base_w: int,
        base_h: int,
        popup_parent: Optional[QWidget] = None,  # 하위 호환용, 무시
        on_click: Optional[Callable[[], None]] = None,
        on_right_click: Optional[Callable[[], None]] = None,
        tooltip: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._on_click = on_click
        self._on_right_click = on_right_click
        self._hi_pixmap: Optional[QPixmap] = None

        self.setFixedSize(base_w, base_h)
        self.setToolTip(tooltip)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(self._STYLE_NORMAL)

    def set_hi_pixmap(self, pixmap: QPixmap) -> None:
        """고화질 픽셀맵을 저장하고 기본 크기로 표시합니다."""
        self._hi_pixmap = pixmap
        lo = pixmap.scaled(
            self.width(), self.height(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        x_off = max(0, (lo.width() - self.width()) // 2)
        y_off = max(0, (lo.height() - self.height()) // 2)
        self.setPixmap(lo.copy(x_off, y_off, self.width(), self.height()))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._hi_pixmap is not None:
            self.set_hi_pixmap(self._hi_pixmap)

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self.setStyleSheet(self._STYLE_HOVER)

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.setStyleSheet(self._STYLE_NORMAL)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._on_click:
            self._on_click()
        elif event.button() == Qt.MouseButton.RightButton and self._on_right_click:
            self._on_right_click()
        super().mousePressEvent(event)


class SidebarWidget(QWidget):
    """게임 오버레이 사이드바 위젯.

    화면 우측에서 슬라이드인하며, 포커스를 빼앗지 않습니다.
    모든 등록 게임에 창 전환·실행/종료·음량을 한 행으로 표시합니다.
    """

    def __init__(
        self,
        data_manager,
        auto_hide_ms: int = _DEFAULT_AUTO_HIDE_MS,
        screen: Optional[QScreen] = None,
        stop_recording: Optional[Callable[[], None]] = None,
        reconnect_recording: Optional[Callable[[], None]] = None,
        get_recording_elapsed: Optional[Callable[[], int]] = None,
        on_hidden: Optional[Callable[[], None]] = None,
        parent: Optional[QWidget] = None,
        on_audio_change: Optional[Callable[[ManagedProcess], bool]] = None,
        audio_state: Optional[Callable] = None,
        on_media_options: Optional[Callable] = None,
        on_media_command: Optional[Callable] = None,
        media_state: Optional[Callable] = None,
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
        self._stop_recording_callback = stop_recording
        self._reconnect_recording = reconnect_recording
        self._get_recording_elapsed = get_recording_elapsed
        self._on_hidden = on_hidden
        self._on_audio_change = on_audio_change
        self._audio_state = audio_state
        self._compact_game_rows = False
        self._on_media_options = on_media_options
        self._on_media_command = on_media_command
        self._media_state = media_state
        self._start_recording_callback: Optional[Callable[[], None]] = None
        self._rec_state = "obs_offline"
        self._rec_elapsed_sec = 0
        self._recording_output_dir: str = ""

        # {process_id: (QLabel, start_timestamp)} — 플레이타임 레이블 트래킹
        self._playtime_labels: dict = {}
        self._thumb_buttons: dict[str, _HoverThumbCell] = {}
        self._thumb_request_id = 0
        self._thumb_cache: dict[str, tuple[float, "QPixmap"]] = {}  # path → (mtime, pixmap)
        self._rec_thumb_buttons: dict[str, _HoverThumbCell] = {}
        self._rec_thumb_request_id = 0
        self._rec_thumb_cache: dict[str, tuple[float, "QPixmap"]] = {}  # path → (mtime, pixmap)

        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(_SIDEBAR_WIDTH)

        self._screen = screen or QApplication.primaryScreen()

        # 내부 프레임 (반투명 배경 + 무테두리 서랍)
        self._frame = QFrame(self)
        self._frame.setObjectName("SidebarFrame")
        self._blur_applied = False
        self._set_frame_background()
        frame_layout = QVBoxLayout(self._frame)
        # 부모 창보다 큰 최소 높이를 강제하지 않고 가운데 스크롤이 부족한 공간을 맡는다.
        frame_layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        padding = round(self.width() * 0.043)
        frame_layout.setContentsMargins(padding, padding, padding, padding)
        frame_layout.setSpacing(round(self.width() * 0.024))

        self._build_ui(frame_layout)
        apply_sidebar_widgets_style(self, dark=True)

        # 슬라이드 애니메이션
        self._anim = QPropertyAnimation(self, b"geometry")
        self._anim.setDuration(_ANIM_DURATION_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.finished.connect(self._on_slide_finished)

        # 자동 숨김 타이머
        self._auto_hide_timer = QTimer(self)
        self._auto_hide_timer.setSingleShot(True)
        self._auto_hide_timer.timeout.connect(self.slide_out)

        # 플레이 시간 갱신 타이머 (1초)
        self._playtime_timer = QTimer(self)
        self._playtime_timer.setInterval(1000)
        self._playtime_timer.timeout.connect(self._refresh_playtime)

        # 실제 시각의 0.5초 경계에 맞춰 기존 시계 타이머를 다시 예약한다.
        self._clock_timer = QTimer(self)
        self._clock_timer.setSingleShot(True)
        self._clock_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._clock_timer.setInterval(500)
        self._clock_timer.timeout.connect(self._update_clock)

        # 녹화 상태 갱신 타이머 (1초)
        self._rec_timer = QTimer(self)
        self._rec_timer.setInterval(1000)
        self._rec_timer.timeout.connect(self._update_rec_timer)

        # 커서 위치 폴링 타이머 (200ms) — leaveEvent 오탐 방지
        self._cursor_poll_timer = QTimer(self)
        self._cursor_poll_timer.setInterval(200)
        self._cursor_poll_timer.timeout.connect(self._poll_cursor)

        # 볼륨 저장 전용 직렬 스레드풀
        self._volume_save_timers: dict = {}
        self._save_pool = QThreadPool()
        self._save_pool.setMaxThreadCount(1)

        # 스크린샷 썸네일 디코딩용 스레드풀
        self._thumb_pool = QThreadPool()
        self._thumb_pool.setMaxThreadCount(2)
        self._thumb_signals = _ThumbnailLoadSignals()
        self._thumb_signals.loaded.connect(self._apply_thumbnail_result)
        self._icon_signals = _IconLoadSignals()
        self._icon_signals.loaded.connect(self._apply_game_icon)

        # 녹화 썸네일 디코딩용 스레드풀 (별도)
        self._rec_thumb_pool = QThreadPool()
        self._rec_thumb_pool.setMaxThreadCount(2)
        self._rec_thumb_signals = _ThumbnailLoadSignals()
        self._rec_thumb_signals.loaded.connect(self._apply_rec_thumbnail_result)

        self._process_stop_signals = _ProcessStopSignals()
        self._process_stop_signals.completed.connect(self._on_process_stop_completed)

        # Win32 외부 클릭 감지 상태
        self._lbutton_was_down: bool = False

    # ------------------------------------------------------------------
    # UI 구성
    # ------------------------------------------------------------------

    def _build_ui(self, layout: QVBoxLayout) -> None:
        """사이드바 내부 위젯을 구성합니다."""
        gap = round(self.width() * 0.024)
        # 시계와 닫기는 휠로 내용이 이동해도 화면 양 끝에 남는다.
        self._clock_widget = QWidget()
        clock_layout = QVBoxLayout(self._clock_widget)
        clock_layout.setContentsMargins(0, round(self.width() * 0.012), 0, gap)
        clock_layout.setSpacing(round(self.width() * 0.012))
        self._clock_face = SidebarClockFace(self.width())
        self._clock_date_label = QLabel()
        self._clock_date_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._clock_date_label.setProperty("hhRole", "sidebarSecondary")
        clock_layout.addWidget(self._clock_face)
        clock_layout.addWidget(self._clock_date_label)
        layout.addWidget(self._clock_widget)

        # 내용이 넘치면 휠로 이동하되 스크롤바와 예약 공간은 만들지 않는다.
        self._main_scroll = QScrollArea()
        self._main_scroll.setWidgetResizable(True)
        self._main_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._main_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._main_scroll.setStyleSheet("""
            QScrollArea { border: none; background: transparent; }
            QWidget#scroll_content { background: transparent; }
        """)

        self._scroll_content = QWidget()
        self._scroll_content.setObjectName("scroll_content")
        self._scroll_layout = QVBoxLayout(self._scroll_content)
        self._scroll_layout.setContentsMargins(0, 0, 0, 0)
        self._scroll_layout.setSpacing(0)

        self._top_section = QWidget()
        top_layout = QVBoxLayout(self._top_section)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(gap)

        top_layout.addWidget(self._section_divider())
        heading = QHBoxLayout()
        row_padding = round(self.width() * 0.015)
        heading.setContentsMargins(0, 0, row_padding, 0)
        heading.setSpacing(round(self.width() * 0.02))
        heading.addWidget(self._media_icon("game"))
        title = QLabel("게임")
        title.setProperty("hhRole", "sidebarSectionTitle")
        heading.addWidget(title)
        heading.addStretch()
        self._volume_heading = QLabel("음량")
        self._volume_heading.setProperty("hhRole", "sidebarSecondary")
        self._volume_heading.setFixedWidth(round(self.width() * 0.114))
        self._volume_heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heading.addWidget(self._volume_heading)
        top_layout.addLayout(heading)
        self._games_list_layout = QVBoxLayout()
        self._games_list_layout.setContentsMargins(0, 0, 0, 0)
        self._games_list_layout.setSpacing(round(self.width() * 0.01))
        top_layout.addLayout(self._games_list_layout)
        self._scroll_layout.addWidget(self._top_section)
        self._scroll_layout.addStretch(1)

        self._media_section = QWidget()
        media_layout = QVBoxLayout(self._media_section)
        media_layout.setContentsMargins(0, gap, 0, 0)
        media_layout.setSpacing(gap)
        media_layout.addWidget(self._section_divider())
        self._media_center_panel = MediaCenterPanel(
            self.width(), on_options=self._on_media_options,
            on_command=self._on_media_command, parent=self._media_section,
        )
        media_layout.addWidget(self._media_center_panel)
        media_layout.addWidget(self._section_divider())

        # 스크린샷 섹션
        self._screenshot_section = self._build_screenshot_section()
        media_layout.addWidget(self._screenshot_section)

        # 녹화 섹션
        self._recording_section = self._build_recording_section()
        media_layout.addWidget(self._recording_section)

        # 파일 종류만 전환한다. 촬영·녹화 조작부는 선택과 독립이다.
        self._gallery_tabs = QTabBar()
        self._gallery_tabs.setExpanding(True)
        self._gallery_tabs.setUsesScrollButtons(False)
        self._gallery_tabs.setDrawBase(False)
        self._gallery_tabs.currentChanged.connect(self._refresh_gallery)
        media_layout.addWidget(self._gallery_tabs)

        self._gallery = QWidget()
        self._gallery.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._gallery_layout = QGridLayout(self._gallery)
        self._gallery_layout.setContentsMargins(0, 0, 0, 0)
        self._gallery_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        # 현재 행의 최소 크기가 다음 높이 감소를 막지 않게 한다.
        self._gallery_layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self._gallery.setFixedHeight(0)
        self._gallery.installEventFilter(self)
        media_layout.addWidget(self._gallery)
        self._scroll_layout.addWidget(self._media_section)
        self._sync_gallery_sources()

        self._main_scroll.setWidget(self._scroll_content)
        self._main_scroll.viewport().installEventFilter(self)
        self._scroll_content.installEventFilter(self)
        layout.addWidget(self._main_scroll, 1)

        # 닫기 버튼 (스크롤 영역 밖, 항상 하단 고정)
        self._close_btn = QPushButton("닫기")
        self._close_btn.setIcon(self._action_icon("close"))
        self._close_btn.clicked.connect(self.slide_out)
        layout.addWidget(self._close_btn)

    def _section_divider(self) -> SidebarDivider:
        return SidebarDivider(self.width())

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
        """등록 게임과 기존 미디어 투영을 갱신하며 실행 상태를 만들어 쓰지 않는다."""
        self._update_clock()
        self._refresh_games()
        self._refresh_screenshot_section()
        self._refresh_recording_section()
        self._refresh_gallery()
        if self._media_state is not None:
            self.update_media_state(self._media_state())

    def update_media_state(self, snapshot) -> None:
        """관측을 투영할 뿐 시작·설정 변경·오디오 native 조회를 수행하지 않는다."""
        self._media_center_panel.update_snapshot(snapshot)
        if snapshot is None or not self.isVisible():
            return
        observations = {item.target.process_id: item for item in snapshot.game_audio}
        processes = {process.id: process for process in self._data_manager.managed_processes}
        for index in range(self._games_list_layout.count()):
            row = self._games_list_layout.itemAt(index).widget()
            process_id = row.property("processId")
            process = processes.get(process_id)
            dial = row.findChild(VolumeDial)
            observation = observations.get(process_id)
            if process is None or dial is None:
                continue
            with QSignalBlocker(dial):
                # 자신의 휠 입력을 worker의 이전 관측값으로 되감지 않는다.
                pending = self._volume_save_timers.get(process_id)
                if (observation is not None and observation.available
                        and observation.volume is not None
                        and not (pending is not None and pending.isActive())):
                    dial.setValue(round(observation.volume * 100 / 5) * 5)
                dial.setChecked(process.default_muted)
            dial._describe_value()
            dial.setToolTip("백그라운드 자동 음소거 · 클릭은 사용자 음소거 설정 변경"
                            if observation is not None and observation.policy_muted
                            else "휠로 5% 조절 · 클릭으로 음소거")

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
        self._media_center_panel.close_options()
        self._playtime_timer.stop()
        self._clock_timer.stop()
        self._cursor_poll_timer.stop()
        self._rec_timer.stop()

        geo = self.geometry()
        end = QRect(geo.x() + _SIDEBAR_WIDTH, geo.y(), geo.width(), geo.height())
        self._anim.setStartValue(geo)
        self._anim.setEndValue(end)
        self._anim.start()

        self._is_shown = False
        logger.debug("SidebarWidget 슬라이드아웃")

    def cleanup(self, deadline_ms: int = 2000) -> bool:
        """타이머와 애니메이션을 정리합니다."""
        self._media_center_panel.close_options()
        self._gallery.removeEventFilter(self)
        self._main_scroll.viewport().removeEventFilter(self)
        self._scroll_content.removeEventFilter(self)
        for timer in self._volume_save_timers.values():
            if timer.isActive():
                timer.stop()
                timer.timeout.emit()
        self._volume_save_timers.clear()
        self._auto_hide_timer.stop()
        self._playtime_timer.stop()
        self._clock_timer.stop()
        self._cursor_poll_timer.stop()
        self._rec_timer.stop()
        self._anim.stop()
        for signals, receiver in (
            (self._thumb_signals, self._apply_thumbnail_result),
            (self._rec_thumb_signals, self._apply_rec_thumbnail_result),
            (self._icon_signals, self._apply_game_icon),
        ):
            try:
                signals.loaded.disconnect(receiver)
            except (TypeError, RuntimeError):
                pass
        deadline = time.monotonic() + max(0, int(deadline_ms)) / 1000.0
        drained = True
        for pool in (self._save_pool, self._thumb_pool, self._rec_thumb_pool):
            pool_drained = pool.waitForDone(max(0, int((deadline - time.monotonic()) * 1000)))
            if not pool_drained:
                retain_detached_qthreadpool(pool)
            drained = drained and pool_drained
        self.hide()
        return drained

    # ------------------------------------------------------------------
    # 이벤트 오버라이드
    # ------------------------------------------------------------------

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._frame.setGeometry(0, 0, self.width(), self.height())

    def eventFilter(self, watched, event) -> bool:
        if watched is getattr(self, "_gallery", None) and event.type() == QEvent.Type.Resize:
            self._layout_gallery()
        elif (watched is self._main_scroll.viewport() and event.type() == QEvent.Type.Resize
              or watched is self._scroll_content and event.type() == QEvent.Type.LayoutRequest):
            self._fit_gallery_height()
        return super().eventFilter(watched, event)

    def _fit_gallery_height(self) -> None:
        """필수 내용 뒤의 가용 높이만 사용하며, 여유 공간은 상·하단 사이에 둔다."""
        height = 0
        viewport = self._main_scroll.viewport()
        width = viewport.width()
        _, cell_height, gap = self._gallery_cell_size(width)
        media_controls_height = (self._media_section.sizeHint().height()
                                 - self._gallery.minimumHeight())
        gallery_minimum = cell_height if not self._gallery.isHidden() else 0
        # 현재 압축된 높이를 기준으로 판단하면 정상/압축 레이아웃이 왕복한다.
        # 원래 전체 문구의 높이로 판단하고 표시만 축약한다.
        self._set_compact_game_rows(
            self._normal_top_height(width) + media_controls_height + gallery_minimum > viewport.height())
        self._fit_compact_row_padding(width, viewport.height() - media_controls_height - gallery_minimum)
        if not self._gallery.isHidden() and self._gallery_layout.count():
            top_layout = self._top_section.layout()
            top_height = (top_layout.totalHeightForWidth(width) if top_layout.hasHeightForWidth()
                          else top_layout.totalSizeHint().height())
            available = viewport.height() - top_height - media_controls_height
            available_rows = max(1, (available + gap) // (cell_height + gap))
            cell_count = len(self._thumb_buttons) + len(self._rec_thumb_buttons) + 1
            rows = min(_THUMB_MAX_ROWS, available_rows, (cell_count + _THUMB_COLS - 1) // _THUMB_COLS)
            height = rows * cell_height + (rows - 1) * gap
        if self._gallery.minimumHeight() != height:
            self._gallery.setFixedHeight(height)

    def _fit_compact_row_padding(self, width: int, available_height: int) -> None:
        """폰트별 실제 높이 뒤에 남는 세로 예산만 게임 행 여백으로 나눈다."""
        if not self._compact_game_rows:
            return
        rows = [self._games_list_layout.itemAt(index).widget()
                for index in range(self._games_list_layout.count())
                if self._games_list_layout.itemAt(index).widget().property("processId") is not None]
        if not rows:
            return
        top = self._top_section.layout()
        current_height = (top.totalHeightForWidth(width) if top.hasHeightForWidth()
                          else top.totalSizeHint().height())
        used_padding = sum(row.layout().contentsMargins().top() + row.layout().contentsMargins().bottom()
                           for row in rows)
        content_height = current_height - used_padding
        normal_padding = round(self.width() * 0.007)
        padding = max(0, min(normal_padding, (available_height - content_height) // (len(rows) * 2)))
        for row in rows:
            layout = row.layout()
            margins = layout.contentsMargins()
            if margins.top() != padding or margins.bottom() != padding:
                layout.setContentsMargins(margins.left(), padding, margins.right(), padding)

    def _normal_top_height(self, width: int) -> int:
        """창 높이와 무관하게, 원래 문구·행 여백에 필요한 높이를 계산한다."""
        normal_padding = round(self.width() * 0.015)
        row_heights = []
        for index in range(self._games_list_layout.count()):
            row = self._games_list_layout.itemAt(index).widget()
            name = row.findChild(QLabel, "gameName")
            if name is None:
                row_heights.append(row.sizeHint().height())
                continue
            row.ensurePolished()
            layout = row.layout()
            text_width = width - normal_padding * 2 - layout.spacing() * (layout.count() - 1)
            controls_height = 0
            for item_index in range(layout.count()):
                item = layout.itemAt(item_index)
                widget = item.widget()
                if widget is not None:
                    text_width -= item.sizeHint().width()
                    controls_height = max(controls_height, item.sizeHint().height())
            text_layout = layout.itemAt(1).layout()
            text_height = 0
            for label_index in range(text_layout.count()):
                label = text_layout.itemAt(label_index).widget()
                full_text = label.toolTip() or label.text()
                text_height += label.fontMetrics().boundingRect(
                    QRect(0, 0, max(1, text_width), 100000),
                    int(Qt.TextFlag.TextWordWrap), full_text).height()
            text_height += text_layout.spacing() * (text_layout.count() - 1)
            row_heights.append(max(controls_height, text_height) + normal_padding * 2)
        games_height = sum(row_heights) + self._games_list_layout.spacing() * max(0, len(row_heights) - 1)
        top = self._top_section.layout()
        margins = top.contentsMargins()
        return (games_height + top.itemAt(0).sizeHint().height()
                + top.itemAt(1).layout().sizeHint().height()
                + top.spacing() * (top.count() - 1) + margins.top() + margins.bottom())

    def _set_compact_game_rows(self, compact: bool, *, force: bool = False) -> None:
        if self._compact_game_rows == compact and not force:
            return
        self._compact_game_rows = compact
        processes = {process.id: process for process in self._data_manager.managed_processes}
        padding = round(self.width() * (0.007 if compact else 0.015))
        for index in range(self._games_list_layout.count()):
            row = self._games_list_layout.itemAt(index).widget()
            process = processes.get(row.property("processId"))
            if process is None:
                continue
            layout = row.layout()
            layout.setContentsMargins(padding, padding, padding, padding)
            name = row.findChild(QLabel, "gameName")
            name.setWordWrap(not compact)
            name.setToolTip(process.name)
            name.setAccessibleDescription(process.name)
            # 가로 공간은 기존 버튼 정사각형과 순서를 보존한 뒤 남는 이름 칸이다.
            text_width = self._main_scroll.viewport().width() - padding * 2 - layout.spacing() * (layout.count() - 1)
            for item_index in range(layout.count()):
                item = layout.itemAt(item_index)
                widget = item.widget()
                if widget is not None:
                    text_width -= item.sizeHint().width()
            name.setText(name.fontMetrics().elidedText(process.name, Qt.TextElideMode.ElideRight,
                                                     max(1, text_width)) if compact else process.name)
            entry = self._playtime_labels.get(process.id)
            if entry is not None:
                label, started, prefix = entry
                label.setWordWrap(not compact)
                self._update_playtime_label(label, started, prefix)

    # ------------------------------------------------------------------
    # 내부 메서드 — 레이아웃
    # ------------------------------------------------------------------

    def _refresh_games(self) -> None:
        """기존 등록 목록과 한 번의 감시 스냅샷으로 게임·음량 행을 만든다."""
        from src.gui.main_window import MainWindow
        self._playtime_labels.clear()
        while self._games_list_layout.count():
            item = self._games_list_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        window = MainWindow.INSTANCE
        active = dict(window.process_monitor.active_monitored_processes) if window else {}
        games = sorted(self._data_manager.managed_processes, key=ManagedProcess.name_sort_key)
        settings = self._data_manager.global_settings
        self._volume_heading.setVisible(getattr(settings, 'sidebar_volume_section_enabled', True))
        for process in games:
            self._games_list_layout.addWidget(self._make_game_row(process, active.get(process.id)))
        if not games:
            label = QLabel("등록된 게임 없음")
            label.setProperty("hhRole", "sidebarSecondary")
            self._games_list_layout.addWidget(label)
        self._set_compact_game_rows(self._compact_game_rows, force=True)

    def _make_game_row(self, process: ManagedProcess, runtime: Optional[dict]) -> QFrame:
        row = QFrame()
        row.setProperty("hhRole", "sidebarGameRow")
        row.setProperty("hhRunning", runtime is not None)
        row.setProperty("processId", process.id)
        row.setProperty("monitoringPath", process.monitoring_path)
        layout = QHBoxLayout(row)
        padding = round(self.width() * 0.015)
        layout.setContentsMargins(padding, padding, padding, padding)
        layout.setSpacing(round(self.width() * 0.015))
        icon_size = round(self.width() * 0.107)
        icon = GameIconLabel(icon_size)
        icon.setText(process.name[:1] or "?")
        icon.setObjectName("gameIcon")
        icon.setFixedSize(icon_size, icon_size)
        icon.setProperty("hhRunning", runtime is not None)
        layout.addWidget(icon)
        self._load_icon_async(process)

        text = QVBoxLayout()
        text.setSpacing(round(self.width() * 0.007))
        name = QLabel(process.name)
        name.setObjectName("gameName")
        name.setProperty("hhRole", "sidebarGameName")
        name.setWordWrap(True)
        name.setToolTip(process.name)
        name.setAccessibleDescription(process.name)
        name.setMinimumWidth(1)
        name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        text.addWidget(name)
        pid = runtime.get("pid") if runtime else None
        created = float(runtime.get("start_time_approx") or 0.0) if runtime else 0.0
        if runtime is not None and getattr(self._data_manager.global_settings, 'sidebar_playtime_enabled', True):
            elapsed = QLabel()
            elapsed.setProperty("hhRole", "sidebarSecondary")
            elapsed.setWordWrap(True)
            elapsed.setMinimumWidth(1)
            elapsed.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            text.addWidget(elapsed)
            prefix = getattr(self._data_manager.global_settings, 'sidebar_playtime_prefix', '오늘 플레이 시간')
            self._playtime_labels[process.id] = (elapsed, created, prefix)
            self._update_playtime_label(elapsed, created, prefix)
        layout.addLayout(text, 1)

        action_size = round(self.width() * 0.114)
        focus = QPushButton()
        focus.setObjectName("focusGame")
        focus.setProperty("hhRole", "sidebarIconAction")
        focus.setFixedSize(action_size, action_size)
        focus.setIcon(self._action_icon("focus"))
        focus.setIconSize(QSize(round(self.width() * 0.046), round(self.width() * 0.046)))
        focus.setAccessibleName(f"{process.name} 창 바로가기")
        focus.setToolTip("창 바로가기")
        focus.setEnabled(pid is not None and created > 0)
        focus.clicked.connect(lambda _=False, key=process.id, path=process.monitoring_path, target=pid, stamp=created: self._focus_process(key, path, target, stamp))
        if runtime is not None:
            layout.addWidget(focus)
        else:
            focus.hide()

        action = QPushButton()
        action.setObjectName("gameAction")
        action.setProperty("hhRole", "sidebarIconAction")
        action.setProperty("hhDanger", runtime is not None)
        action.setFixedSize(action_size, action_size)
        action.setIcon(self._action_icon("stop" if runtime is not None else "launch"))
        action.setIconSize(focus.iconSize())
        action.setAccessibleName(f"{process.name} {'종료' if runtime is not None else '실행'}")
        action.setToolTip("게임 종료" if runtime is not None else "게임 실행")
        if runtime is not None:
            action.setEnabled(pid is not None and created > 0)
            action.clicked.connect(lambda _=False, key=process.id, path=process.monitoring_path, target=pid, stamp=created: self._kill_process(key, path, target, stamp))
        else:
            action.clicked.connect(lambda _=False, key=process.id, path=process.monitoring_path: self._launch_process(key, path))
        layout.addWidget(action)
        dial = self._make_volume_dial(process, pid)
        layout.addWidget(dial)
        # 부모 없는 조작부를 먼저 show하면 잠깐 독립 네이티브 창으로 나타난다.
        dial.setVisible(getattr(self._data_manager.global_settings, 'sidebar_volume_section_enabled', True))
        return row

    def _launch_process(self, process_id: str, monitoring_path: str) -> None:
        from src.gui.main_window import MainWindow
        window = MainWindow.INSTANCE
        process = next((p for p in self._data_manager.managed_processes
                        if p.id == process_id and p.monitoring_path == monitoring_path), None)
        if (process is None or window is None or window._shutting_down
                or window._beholder_restore_runtime_suspended):
            logger.warning("사이드바 실행 취소: 등록 대상 또는 앱 준비 상태 변경 (등록=%s)", process_id)
            return
        target, mode = window._resolve_process_launch_target(process)
        if not target:
            logger.warning("사이드바 실행 경로 없음: 등록=%s", process_id)
            return
        args = resolve_launch_args(process, mode, target)
        QThreadPool.globalInstance().start(_ProcessLaunchTask(
            process_id, target, mode, args,
            bool(self._data_manager.global_settings.run_as_admin), window._lifecycle_shutdown_event,
        ))
        self._reset_auto_hide()

    def _focus_process(self, process_id: str, monitoring_path: str, pid: Optional[int], create_time: float) -> None:
        process = next((p for p in self._data_manager.managed_processes
                        if p.id == process_id and p.monitoring_path == monitoring_path), None)
        if process is None or pid is None or create_time <= 0:
            logger.warning("사이드바 창 전환 취소: 등록 대상 또는 실행 정보 변경 (등록=%s)", process_id)
            return
        if focus_managed_process_window(pid, create_time, monitoring_path):
            self.slide_out()
        else:
            logger.warning("사이드바 창 전환 실패: 등록=%s PID=%s", process_id, pid)
            self._reset_auto_hide()

    def _kill_process(self, process_id: str, monitoring_path: str,
                      pid: Optional[int], create_time: float) -> None:
        """등록 대상과 기존 관측 identity를 확정하고 종료를 비동기로 요청합니다."""
        process = next((item for item in self._data_manager.managed_processes
                        if item.id == process_id and item.monitoring_path == monitoring_path), None)
        if process is None or pid is None or create_time <= 0:
            logger.warning("사이드바 게임 종료 요청 취소: 등록 대상 또는 실행 정보 변경 (등록=%s 경로=%s PID=%s 생성=%s)",
                           process_id, monitoring_path, pid, create_time)
            return
        snapshot = ManagedProcess(
            id=process.id, name=process.name, monitoring_path=process.monitoring_path,
            launch_path=process.launch_path,
        )
        run_as_admin = bool(getattr(self._data_manager.global_settings, "run_as_admin", False))
        self._auto_hide_timer.stop()
        QThreadPool.globalInstance().start(_ProcessStopTask(
            snapshot, int(pid), float(create_time), run_as_admin, self._process_stop_signals
        ))

    @Slot()
    def _on_process_stop_completed(self) -> None:
        # A successful termination call still allows delayed OS cleanup. The
        # existing process monitor removes the game when it actually disappears.
        self._reset_auto_hide()

    # ------------------------------------------------------------------
    # 내부 메서드 — 플레이타임
    # ------------------------------------------------------------------

    def _update_playtime_label(self, label: QLabel, start_ts: float, prefix: str = "오늘 플레이 시간") -> None:
        """경과 시간을 계산해 레이블 텍스트를 갱신합니다."""
        elapsed = int(time.time() - start_ts) if start_ts else 0
        h = elapsed // 3600
        m = (elapsed % 3600) // 60
        if h > 0:
            elapsed_text = f"{h}시간 {m:02d}분"
        else:
            elapsed_text = f"{m}분"
        full_text = f"{prefix}: {elapsed_text}"
        label.setToolTip(full_text)
        label.setAccessibleDescription(full_text)
        label.setText(elapsed_text if self._compact_game_rows else full_text)

    def _refresh_playtime(self) -> None:
        """1초 타이머마다 모든 실행 중 게임의 플레이타임 레이블을 갱신합니다."""
        for entry in self._playtime_labels.values():
            label, start_ts, prefix = entry
            self._update_playtime_label(label, start_ts, prefix)

    def _update_clock(self) -> None:
        import datetime
        now = datetime.datetime.now()
        self._clock_face.set_time(now)
        weekday = ("월", "화", "수", "목", "금", "토", "일")[now.weekday()]
        self._clock_date_label.setText(f"{now.month}월 {now.day}일 {weekday}요일")
        self._clock_widget.setVisible(getattr(self._data_manager.global_settings, 'sidebar_clock_enabled', True))
        if self._is_shown:
            self._clock_timer.start(500 - (now.microsecond // 1000) % 500)

    def _load_icon_async(self, process: ManagedProcess) -> None:
        self._thumb_pool.start(_IconLoadTask(process.id, process.monitoring_path, self._icon_signals))

    @Slot(str, str, object)
    def _apply_game_icon(self, process_id: str, path: str, image) -> None:
        if image is None:
            return
        for index in range(self._games_list_layout.count()):
            row = self._games_list_layout.itemAt(index).widget()
            if row.property("processId") == process_id and row.property("monitoringPath") == path:
                label = row.findChild(QLabel, "gameIcon")
                label.setPixmap(QPixmap.fromImage(image))
                return

    def _make_volume_dial(self, process: ManagedProcess, pid: Optional[int]) -> VolumeDial:
        dial = VolumeDial(round(self.width() * 0.114))
        dial.setAccessibleName(f"{process.name} 음량")
        value = process.default_volume if process.default_volume is not None else 100
        muted = process.default_muted
        policy_active, observation = self._audio_state(process.id) if self._audio_state else (False, None)
        if policy_active:
            if observation is not None and observation.available and observation.volume is not None:
                value = round(observation.volume * 100 / 5) * 5
            if observation is not None and observation.policy_muted:
                dial.setToolTip("백그라운드 자동 음소거 · 클릭은 사용자 음소거 설정 변경")
        elif pid is not None:
            try:
                actual = audio_control.get_app_volume(pid)
                actual_muted = audio_control.is_muted(pid)
                if actual is not None:
                    value = round(actual * 100 / 5) * 5
                if actual_muted is not None:
                    muted = actual_muted
            except Exception:
                logger.debug("게임 음량 조회 실패: 등록=%s PID=%s", process.id, pid, exc_info=True)
        dial.setValue(value)
        dial.setChecked(muted)
        dial.valueChanged.connect(lambda value, p=process, target=pid: self._set_game_volume(value, p, target))
        dial.toggled.connect(lambda muted, p=process, target=pid: self._set_game_muted(muted, p, target))
        dial.interacted.connect(self._reset_auto_hide)
        return dial

    def _set_game_volume(self, value: int, process: ManagedProcess, pid: Optional[int]) -> None:
        process.default_volume = value
        handled = bool(self._on_audio_change and self._on_audio_change(process))
        if pid is not None and not handled:
            audio_control.set_app_volume(pid, value / 100.0)
        self._schedule_volume_save(process)
        self._reset_auto_hide()

    def _set_game_muted(self, muted: bool, process: ManagedProcess, pid: Optional[int]) -> None:
        process.default_muted = muted
        handled = bool(self._on_audio_change and self._on_audio_change(process))
        if pid is not None and not handled:
            audio_control.set_mute(pid, muted)
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
        geo = screen.availableGeometry()
        logical = screen.geometry()
        native = get_visible_taskbar_work_area((logical.left(), logical.top()), int(self.winId()))
        if native is not None:
            monitor, work = native
            scale_x = logical.width() / (monitor[2] - monitor[0])
            scale_y = logical.height() / (monitor[3] - monitor[1])
            x1 = logical.left() + round((work[0] - monitor[0]) * scale_x)
            y1 = logical.top() + round((work[1] - monitor[1]) * scale_y)
            x2 = logical.left() + round((work[2] - monitor[0]) * scale_x)
            y2 = logical.top() + round((work[3] - monitor[1]) * scale_y)
            geo = QRect(x1, y1, x2 - x1, y2 - y1)
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
        self.setWindowOpacity(1.0)
        if self._is_shown:
            geo = self._compute_geometry()
            self.setGeometry(geo)

    def _set_frame_background(self) -> None:
        red, green, blue, alpha = ACRYLIC_TINT
        if self._blur_applied:
            alpha = 0  # native tint 위에 두 번째 어두운 막을 그리지 않는다.
        self._frame.setStyleSheet(
            f"QFrame#SidebarFrame {{ background-color: rgba({red},{green},{blue},{alpha});"
            " border: none; border-radius: 0px; }"
        )

    def _reset_auto_hide(self) -> None:
        if self._auto_hide_ms > 0:
            self._auto_hide_timer.start(self._auto_hide_ms)

    def _poll_cursor(self) -> None:
        from PySide6.QtGui import QCursor
        # 열기·닫기 전환의 화면 밖 좌표를 사용자 이탈로 판단하지 않는다.
        if self._anim.state() == QPropertyAnimation.State.Running:
            return
        if self._is_shown:
            geo = self._compute_geometry()
            if self.geometry() != geo:
                self.setGeometry(geo)
        cursor_pos = QCursor.pos()
        inside = self.rect().contains(self.mapFromGlobal(cursor_pos))
        if self._media_center_panel.options_open:
            self._auto_hide_timer.stop()
            return

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
        section.setMinimumHeight(round(self.width() * 0.1))
        header = QHBoxLayout(section)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(round(self.width() * 0.02))
        title = QLabel("스크린샷")
        title.setProperty("hhRole", "sidebarSectionTitle")
        self._capture_now_btn = QPushButton("지금 촬영")
        self._capture_now_btn.clicked.connect(self._on_capture_now_clicked)
        header.addWidget(self._media_icon("screenshot"))
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self._capture_now_btn)
        return section

    def _build_recording_section(self) -> QWidget:
        """녹화 상태 섹션 위젯을 구성합니다."""
        section = QWidget()
        section.setMinimumHeight(round(self.width() * 0.1))
        header = QHBoxLayout(section)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(round(self.width() * 0.02))
        title = QLabel("녹화")
        title.setProperty("hhRole", "sidebarSectionTitle")
        header.addWidget(self._media_icon("recording"))
        header.addWidget(title)
        header.addStretch()

        self._rec_status_label = QLabel("연결 안 됨")
        self._rec_status_label.setProperty("hhRole", "sidebarSecondary")
        self._rec_status_label.setProperty("hhState", "default")
        header.addWidget(self._rec_status_label)

        self._rec_start_btn = QPushButton("녹화 시작")
        self._rec_start_btn.clicked.connect(self._on_rec_start_clicked)
        self._rec_start_btn.hide()
        header.addWidget(self._rec_start_btn)

        self._rec_stop_btn = QPushButton("녹화 종료")
        self._rec_stop_btn.setProperty("hhRole", "danger")
        self._rec_stop_btn.clicked.connect(self._on_rec_stop_clicked)
        self._rec_stop_btn.hide()
        header.addWidget(self._rec_stop_btn)

        # OBS 재연결 버튼 (obs_offline 상태에서만 표시)
        self._rec_connect_btn = QPushButton("재연결")
        self._rec_connect_btn.clicked.connect(self._on_rec_connect_clicked)
        header.addWidget(self._rec_connect_btn)

        return section

    def _media_icon(self, kind: str) -> QLabel:
        """같은 선 굵기의 섹션 아이콘을 표시한다."""
        size = round(self.width() * 0.05)
        label = QLabel()
        label.setFixedSize(size, size)
        label.setPixmap(self._action_icon(kind).pixmap(size, size))
        return label

    def _action_icon(self, kind: str) -> QIcon:
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QPainter, QPainterPath, QPen
        size = round(self.width() * 0.05)
        pixmap = QPixmap(size * 2, size * 2)
        pixmap.setDevicePixelRatio(2)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(size / 16, size / 16)
        painter.setPen(QPen(QColor("#e8a7b1" if kind == "stop" else "#f5f5f6"), 1.2))
        if kind == "screenshot":
            painter.drawRoundedRect(QRectF(1, 4, 14, 10), 1.5, 1.5)
            painter.drawEllipse(QRectF(5, 6, 6, 6))
            painter.drawRect(QRectF(5, 2, 6, 2))
        elif kind == "recording":
            painter.drawRoundedRect(QRectF(1, 4, 9, 8), 1.5, 1.5)
            path = QPainterPath()
            path.moveTo(10, 6)
            path.lineTo(15, 3)
            path.lineTo(15, 13)
            path.lineTo(10, 10)
            painter.drawPath(path)
        elif kind == "game":
            painter.drawRoundedRect(QRectF(1, 4, 14, 9), 2.5, 2.5)
            painter.drawLine(3, 8, 7, 8)
            painter.drawLine(5, 6, 5, 10)
            painter.drawEllipse(QRectF(10, 7, 1, 1))
            painter.drawEllipse(QRectF(12, 9, 1, 1))
        elif kind == "launch":
            path = QPainterPath()
            path.moveTo(4, 2)
            path.lineTo(13, 8)
            path.lineTo(4, 14)
            path.closeSubpath()
            painter.drawPath(path)
        elif kind == "stop":
            painter.drawArc(QRectF(2, 3, 12, 12), 135 * 16, 270 * 16)
            painter.drawLine(8, 1, 8, 8)
        elif kind == "focus":
            for x, y, dx, dy in ((2, 2, 4, 4), (14, 2, -4, 4),
                                  (2, 14, 4, -4), (14, 14, -4, -4)):
                painter.drawLine(x, y, x + dx, y)
                painter.drawLine(x, y, x, y + dy)
            painter.drawEllipse(QRectF(5.5, 5.5, 5, 5))
        elif kind == "close":
            painter.drawLine(6, 3, 11, 8)
            painter.drawLine(11, 8, 6, 13)
        painter.end()
        return QIcon(pixmap)

    def set_on_stop_recording(self, fn) -> None:
        """녹화 종료 버튼 클릭 시 호출될 콜백을 등록합니다."""
        self._stop_recording_callback = fn

    def set_on_reconnect_recording(self, fn: Optional[Callable[[], None]]) -> None:
        """녹화 재연결 버튼 클릭 시 호출될 콜백을 등록합니다."""
        self._reconnect_recording = fn

    def set_recording_elapsed_provider(self, fn: Optional[Callable[[], int]]) -> None:
        """현재 녹화 경과 시간을 초 단위로 제공하는 콜백을 등록합니다."""
        self._get_recording_elapsed = fn

    def set_on_start_recording(self, fn: Optional[Callable[[], None]]) -> None:
        """[녹화 시작] 버튼 클릭 시 호출될 콜백을 등록합니다."""
        self._start_recording_callback = fn

    def set_recording_output_dir(self, path: str) -> None:
        """녹화 출력 폴더 경로를 설정하고 갤러리를 갱신합니다."""
        self._recording_output_dir = path
        self._refresh_recording_thumbnails()

    def on_recording_state_changed(self, state: str) -> None:
        """MainWindow에서 호출하는 슬롯. state: 'idle'|'recording'|'connecting'|'obs_offline'"""
        self._rec_state = state
        if state != "recording":
            self._rec_elapsed_sec = 0
        self._update_rec_ui()

    def _update_rec_ui(self) -> None:
        state = getattr(self, '_rec_state', 'obs_offline')
        elapsed = getattr(self, '_rec_elapsed_sec', 0)
        gs = getattr(self._data_manager, 'global_settings', None)
        control_enabled = bool(getattr(gs, 'recording_enabled', False))
        self._rec_status_label.setVisible(control_enabled)
        if state == "recording":
            if self._get_recording_elapsed:
                elapsed = max(0, int(self._get_recording_elapsed()))
                self._rec_elapsed_sec = elapsed
            mins, secs = divmod(elapsed, 60)
            hrs, mins = divmod(mins, 60)
            self._rec_status_label.setText(f"{hrs:02d}:{mins:02d}:{secs:02d}")
            status_style = "error"
            self._rec_stop_btn.setVisible(control_enabled)
            self._rec_start_btn.hide()
            self._rec_connect_btn.hide()
        elif state == "idle":
            self._rec_status_label.setText("연결됨")
            status_style = "success"
            self._rec_stop_btn.hide()
            self._rec_start_btn.setVisible(control_enabled)
            self._rec_connect_btn.hide()
        elif state == "connecting":
            self._rec_status_label.setText("연결 중")
            status_style = "warning"
            self._rec_stop_btn.hide()
            self._rec_start_btn.hide()
            self._rec_connect_btn.hide()
        else:  # obs_offline
            self._rec_status_label.setText("연결 안 됨")
            status_style = "default"
            self._rec_stop_btn.hide()
            self._rec_start_btn.hide()
            self._rec_connect_btn.setVisible(control_enabled)
        self._rec_status_label.setProperty("hhState", status_style)
        self._rec_status_label.style().unpolish(self._rec_status_label)
        self._rec_status_label.style().polish(self._rec_status_label)

    def _update_rec_timer(self) -> None:
        """1초 tick. recording 상태일 때 표시 시간을 갱신."""
        if getattr(self, '_rec_state', '') == "recording":
            self._update_rec_ui()

    def _on_rec_stop_clicked(self) -> None:
        if self._stop_recording_callback:
            self._stop_recording_callback()

    def _on_rec_connect_clicked(self) -> None:
        """OBS 재연결 버튼 클릭 — 연결만 시도하고 녹화는 시작하지 않는다."""
        if self._reconnect_recording:
            self._reconnect_recording()

    def _on_rec_start_clicked(self) -> None:
        """[녹화 시작] 버튼 클릭 — 카운트다운 콜백을 호출합니다."""
        if self._start_recording_callback:
            self._start_recording_callback()

    def _refresh_recording_section(self) -> None:
        """Recording controls and the existing-file gallery have separate switches."""
        gs = getattr(self._data_manager, 'global_settings', None)
        enabled = getattr(gs, 'recording_enabled', False) if gs else False
        files_enabled = getattr(gs, 'obs_watch_output_dir', True) if gs else False
        self._recording_section.setVisible(enabled or files_enabled)
        self._update_rec_ui()
        self._sync_gallery_sources()

    def _refresh_screenshot_section(self) -> None:
        """스크린샷 섹션 표시 여부를 설정에 따라 갱신합니다."""
        gs = getattr(self._data_manager, 'global_settings', None)
        enabled = getattr(gs, 'screenshot_enabled', True) if gs else True
        self._screenshot_section.setVisible(enabled)
        # 캡처 버튼 활성화 여부 (ScreenshotManager 참조는 MainWindow에 있으므로 항상 활성)
        self._capture_now_btn.setEnabled(True)
        self._sync_gallery_sources()

    def _sync_gallery_sources(self) -> None:
        """설정에서 허용한 파일 종류만 표시하고 가능한 기존 선택을 유지한다."""
        gs = getattr(self._data_manager, "global_settings", None)
        choices = []
        if getattr(gs, "screenshot_enabled", True):
            choices.append(("screenshot", "스크린샷"))
        if gs and getattr(gs, "obs_watch_output_dir", True):
            choices.append(("recording", "녹화"))
        tabs = self._gallery_tabs
        current = tabs.tabData(tabs.currentIndex())
        if [tabs.tabData(index) for index in range(tabs.count())] != [key for key, _ in choices]:
            tabs.blockSignals(True)
            while tabs.count():
                tabs.removeTab(0)
            for key, label in choices:
                tabs.setTabData(tabs.addTab(label), key)
            selected = next((index for index, (key, _) in enumerate(choices) if key == current), 0)
            tabs.setCurrentIndex(selected)
            tabs.blockSignals(False)
            self._refresh_gallery()
        tabs.setVisible(bool(choices))
        self._gallery.setVisible(bool(choices))

    def _gallery_cell_size(self, width: Optional[int] = None) -> tuple[int, int, int]:
        """3열·4:3 셀과 간격을 현재 공용 영역 너비로 계산한다."""
        if width is None:
            width = self._gallery.width()
        gap = max(1, round(width / 80))
        cell_width = max(1, (width - gap * (_THUMB_COLS - 1)) // _THUMB_COLS)
        return cell_width, max(1, round(cell_width * 0.75)), gap

    def _refresh_gallery(self, _index: int = -1) -> None:
        """콘텐츠 진입점에서만 파일을 읽고 최대 5개 미리보기를 준비한다."""
        if not hasattr(self, "_thumb_pool"):
            return  # UI 구성 중에는 디코딩 작업을 등록하지 않는다.
        self._thumb_request_id += 1
        self._rec_thumb_request_id += 1
        for cell in self._gallery.findChildren(QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly):
            cell.hide()
            cell.deleteLater()
        self._thumb_buttons.clear()
        self._rec_thumb_buttons.clear()
        while self._gallery_layout.count():
            self._gallery_layout.takeAt(0)

        kind = self._gallery_tabs.tabData(self._gallery_tabs.currentIndex())
        if kind is None:
            self._fit_gallery_height()
            return
        cell_width, cell_height, gap = self._gallery_cell_size()
        self._fit_gallery_height()
        self._gallery_layout.setSpacing(gap)

        if kind == "screenshot":
            gs = getattr(self._data_manager, "global_settings", None)
            output_dir = getattr(gs, "screenshot_save_dir", "")
            if not output_dir:
                from src.screenshot.capture import _DEFAULT_SAVE_DIR
                output_dir = str(_DEFAULT_SAVE_DIR)
            extensions = (".png", ".jpg", ".jpeg", ".bmp")
            make_cell = self._make_thumb_cell
            request_id = self._thumb_request_id
            cache = self._thumb_cache
            folder_tip = "스크린샷 폴더 열기"
        else:
            output_dir = self._recording_output_dir
            extensions = (".mp4",)
            make_cell = self._make_rec_thumb_cell
            request_id = self._rec_thumb_request_id
            cache = self._rec_thumb_cache
            folder_tip = "녹화 폴더 열기"
        if not output_dir:
            return
        folder = Path(output_dir)
        try:
            if not folder.is_dir():
                return
            files = sorted((path for path in folder.iterdir() if path.suffix.lower() in extensions and path.is_file()),
                           key=lambda path: path.stat().st_mtime, reverse=True)
        except OSError:
            logger.exception("갤러리 파일 조회 실패: %s", output_dir)
            return

        shown = files[:_THUMB_MAX_ROWS * _THUMB_COLS - 1]
        for index, path in enumerate(shown):
            self._gallery_layout.addWidget(make_cell(path, request_id), *divmod(index, _THUMB_COLS))
        remaining = len(files) - len(shown)
        folder_btn = QPushButton(f"+{remaining}" if remaining else "")
        folder_btn.setFixedSize(cell_width, cell_height)
        folder_btn.setToolTip(folder_tip)
        folder_btn.setProperty("hhRole", "folderAction")
        if not remaining:
            folder_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))

        def open_folder() -> None:
            if folder.is_dir():
                os.startfile(str(folder))
            else:
                logger.warning("갤러리 폴더가 존재하지 않습니다: %s", folder)

        folder_btn.clicked.connect(open_folder)
        self._gallery_layout.addWidget(folder_btn, *divmod(len(shown), _THUMB_COLS))
        self._fit_gallery_height()
        self._layout_gallery(file_count=len(files))
        shown_paths = {str(path) for path in shown}
        for path in list(cache):
            if path not in shown_paths:
                del cache[path]

    def _layout_gallery(self, *, file_count: Optional[int] = None) -> None:
        """크기 변경은 기존 셀만 재배치한다. 파일 조회·디코딩·요청 갱신 없음."""
        if not self._gallery_layout.count():
            return
        cells = list(self._thumb_buttons.values()) + list(self._rec_thumb_buttons.values())
        folder = self._gallery_layout.itemAt(self._gallery_layout.count() - 1).widget()
        if file_count is None:
            omitted = int(folder.text()[1:]) if folder.text().startswith("+") else 0
            file_count = omitted + sum(not cell.isHidden() for cell in cells)
        width, height, gap = self._gallery_cell_size()
        self._gallery_layout.setSpacing(gap)
        rows = min(_THUMB_MAX_ROWS, max(1, (self._gallery.height() + gap) // (height + gap)))
        shown_count = min(len(cells), rows * _THUMB_COLS - 1)
        while self._gallery_layout.count():
            self._gallery_layout.takeAt(0)
        for index, cell in enumerate(cells):
            cell.setFixedSize(width, height)
            cell.setVisible(index < shown_count)
            if index < shown_count:
                self._gallery_layout.addWidget(cell, *divmod(index, _THUMB_COLS))
        folder.setFixedSize(width, height)
        remaining = file_count - shown_count
        folder.setText(f"+{remaining}" if remaining else "")
        folder.setIcon(QIcon() if remaining else self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))
        self._gallery_layout.addWidget(folder, *divmod(shown_count, _THUMB_COLS))

    @Slot()
    def _refresh_screenshot_thumbnails(self) -> None:
        if self._gallery_tabs.tabData(self._gallery_tabs.currentIndex()) == "screenshot":
            self._refresh_gallery()

    def _make_thumb_cell(self, filepath, request_id: int) -> _HoverThumbCell:
        """썸네일 셀 _HoverThumbCell을 반환합니다."""
        path_str = str(filepath)

        def _open() -> None:
            os.startfile(path_str)

        def _show_context_menu() -> None:
            from PySide6.QtWidgets import QMenu, QMessageBox
            from PySide6.QtGui import QCursor
            menu = QMenu()
            menu.setStyleSheet("""
                QMenu {
                    background: #1e1e2a; color: white;
                    border: 1px solid rgba(255,255,255,30);
                    border-radius: 4px; padding: 2px;
                }
                QMenu::item { padding: 5px 18px; border-radius: 3px; }
                QMenu::item:selected { background: rgba(255,255,255,15); }
            """)
            copy_act = menu.addAction("복사")
            menu.addSeparator()
            del_act = menu.addAction("삭제")
            action = menu.exec(QCursor.pos())
            if action == copy_act:
                _copy_file(path_str)
            elif action == del_act:
                _delete_file(path_str)

        def _copy_file(path: str) -> None:
            copy_file_to_clipboard(path)

        def _delete_file(path: str) -> None:
            self._delete_gallery_file(
                path,
                cache=self._thumb_cache,
                refresh=self._refresh_screenshot_thumbnails,
            )

        cell = _HoverThumbCell(
            *self._gallery_cell_size()[:2],
            popup_parent=self._frame,
            on_click=_open,
            on_right_click=_show_context_menu,
            tooltip=filepath.name,
        )
        self._thumb_buttons[path_str] = cell

        # 캐시 히트 시 즉시 표시, 미스 시 비동기 로드
        try:
            mtime = filepath.stat().st_mtime
            cached = self._thumb_cache.get(path_str)
            if cached and cached[0] == mtime:
                cell.set_hi_pixmap(cached[1])
                return cell
        except OSError:
            pass

        self._thumb_pool.start(_ThumbnailLoadTask(request_id, path_str, self._thumb_signals))
        return cell

    def _delete_gallery_file(
        self,
        path: str,
        *,
        cache: dict,
        refresh: Callable[[], None],
    ) -> None:
        from PySide6.QtWidgets import QMessageBox

        reply = QMessageBox.question(
            self,
            "삭제 확인",
            f"'{Path(path).name}'을(를) 휴지통으로 이동하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            import winshell

            winshell.delete_file(path, allow_undo=True, no_confirm=True, silent=True)
        except Exception:
            logger.exception("파일 휴지통 이동 실패: %s", path)
            return

        cache.pop(path, None)
        refresh()

    @Slot(int, str, object)
    def _apply_thumbnail_result(self, request_id: int, filepath: str, image: object) -> None:
        if request_id != self._thumb_request_id:
            return
        cell = self._thumb_buttons.get(filepath)
        if cell is None or image is None:
            return
        try:
            pixmap = QPixmap.fromImage(image)
            if pixmap.isNull():
                return
            cell.set_hi_pixmap(pixmap)
            # 캐시에 저장
            try:
                from pathlib import Path
                mtime = Path(filepath).stat().st_mtime
                self._thumb_cache[filepath] = (mtime, pixmap)
            except OSError:
                pass
        except Exception:
            logger.exception("썸네일 적용 실패: %s", filepath)

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
        from PySide6.QtCore import QMetaObject, Qt
        QMetaObject.invokeMethod(
            self, "_refresh_screenshot_thumbnails",
            Qt.ConnectionType.QueuedConnection,
        )

    @Slot()
    def _refresh_recording_thumbnails(self) -> None:
        if self._gallery_tabs.tabData(self._gallery_tabs.currentIndex()) == "recording":
            self._refresh_gallery()

    def _make_rec_thumb_cell(self, filepath, request_id: int) -> _HoverThumbCell:
        """녹화 썸네일 셀 _HoverThumbCell을 반환합니다."""
        path_str = str(filepath)

        def _open() -> None:
            os.startfile(path_str)

        def _show_context_menu() -> None:
            from PySide6.QtWidgets import QMenu
            from PySide6.QtGui import QCursor

            menu = QMenu()
            menu.setStyleSheet("""
                QMenu {
                    background: #1e1e2a; color: white;
                    border: 1px solid rgba(255,255,255,30);
                    border-radius: 4px; padding: 2px;
                }
                QMenu::item { padding: 5px 18px; border-radius: 3px; }
                QMenu::item:selected { background: rgba(255,255,255,15); }
            """)
            del_act = menu.addAction("삭제")
            action = menu.exec(QCursor.pos())
            if action == del_act:
                self._delete_gallery_file(
                    path_str,
                    cache=self._rec_thumb_cache,
                    refresh=self._refresh_recording_thumbnails,
                )

        cell = _HoverThumbCell(
            *self._gallery_cell_size()[:2],
            popup_parent=self._frame,
            on_click=_open,
            on_right_click=_show_context_menu,
            tooltip=filepath.name,
        )
        self._rec_thumb_buttons[path_str] = cell

        # 캐시 히트 시 즉시 표시, 미스 시 비동기 로드
        try:
            mtime = filepath.stat().st_mtime
            cached = self._rec_thumb_cache.get(path_str)
            if cached and cached[0] == mtime:
                cell.set_hi_pixmap(cached[1])
                return cell
        except OSError:
            pass

        self._rec_thumb_pool.start(
            _VideoThumbnailLoadTask(request_id, path_str, self._rec_thumb_signals)
        )
        return cell

    @Slot(int, str, object)
    def _apply_rec_thumbnail_result(self, request_id: int, filepath: str, image: object) -> None:
        if request_id != self._rec_thumb_request_id:
            return
        cell = self._rec_thumb_buttons.get(filepath)
        if cell is None or image is None:
            return
        try:
            pixmap = QPixmap.fromImage(image)
            if pixmap.isNull():
                return
            cell.set_hi_pixmap(pixmap)
            # 캐시에 저장
            try:
                from pathlib import Path
                mtime = Path(filepath).stat().st_mtime
                self._rec_thumb_cache[filepath] = (mtime, pixmap)
            except OSError:
                pass
        except Exception:
            logger.exception("녹화 썸네일 적용 실패: %s", filepath)

    def _on_slide_finished(self) -> None:
        # 같은 애니메이션의 완료는 현재의 열기/닫기 의도만 소비한다.
        if self._is_shown:
            return
        self.hide()
        if self._on_hidden is not None:
            try:
                self._on_hidden()
            except Exception:
                logger.exception("SidebarWidget 숨김 콜백 예외")

    def _try_apply_blur(self) -> None:
        try:
            from src.gui.sidebar.win32_effects import apply_blur_effect
            hwnd = int(self.winId())
            self._blur_applied = apply_blur_effect(hwnd)
            self._set_frame_background()
            if not self._blur_applied:
                logger.warning("사이드바 Acrylic 적용 실패: 고정 반투명 배경 유지 (hwnd=%s)", hwnd)
        except Exception:
            logger.debug("사이드바 블러 효과 적용 실패", exc_info=True)
