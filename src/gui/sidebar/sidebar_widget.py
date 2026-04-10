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
    Qt, QAbstractAnimation, QObject, QPropertyAnimation, QEasingCurve,
    QPoint, QRect, QTimer, QRunnable, QThreadPool, pyqtSignal, pyqtSlot,
)
from PyQt6.QtGui import QScreen, QColor, QIcon, QImage, QPixmap
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

# 스크린샷/녹화 썸네일 크기 (px)
_THUMB_W = 76
_THUMB_H = 57
_THUMB_COLS = 3
_THUMB_MAX_CELLS = _THUMB_COLS * 3  # 최대 9셀 (마지막 1셀은 폴더 버튼)

# 고화질 썸네일 로드 크기 (hover 확대 시 선명도 확보)
_THUMB_HIRES_W = _THUMB_W * 2   # 152px
_THUMB_HIRES_H = _THUMB_H * 2   # 114px


class _ThumbnailLoadSignals(QObject):
    loaded = pyqtSignal(int, str, object)


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
        try:
            import ctypes
            import ctypes.wintypes as wintypes
            from ctypes import POINTER, byref, c_int, c_uint, c_void_p, c_wchar_p

            shell32 = ctypes.windll.shell32
            ole32 = ctypes.windll.ole32
            gdi32 = ctypes.windll.gdi32
            user32 = ctypes.windll.user32

            ole32.CoInitializeEx(None, 0)  # COINIT_APARTMENTTHREADED

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
            Release_si = ctypes.WINFUNCTYPE(c_uint, c_void_p)(vtbl[0][2])

            psiif = c_void_p()
            hr = QI_fn(psi, byref(IID_ISIIF), byref(psiif))
            Release_si(psi)

            if hr != 0 or not psiif:
                return None

            class _SIZE(ctypes.Structure):
                _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]

            vtbl2 = ctypes.cast(psiif, POINTER(POINTER(c_void_p)))
            GetImage_fn = ctypes.WINFUNCTYPE(c_int, c_void_p, _SIZE, c_uint, POINTER(wintypes.HBITMAP))(vtbl2[0][3])
            Release_siif = ctypes.WINFUNCTYPE(c_uint, c_void_p)(vtbl2[0][2])

            SIIGBF_BIGGERSIZEOK = 0x1
            hbm = wintypes.HBITMAP()
            hr = GetImage_fn(psiif, _SIZE(w, h), SIIGBF_BIGGERSIZEOK, byref(hbm))
            Release_siif(psiif)

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
            bih = _BITMAPINFOHEADER()
            bih.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
            bih.biWidth = w
            bih.biHeight = -h  # top-down DIB
            bih.biPlanes = 1
            bih.biBitCount = 32
            bih.biCompression = 0  # BI_RGB

            buf = ctypes.create_string_buffer(w * h * 4)
            gdi32.GetDIBits(hdc, hbm, 0, h, buf, byref(bih), 0)
            user32.ReleaseDC(0, hdc)
            gdi32.DeleteObject(hbm)

            img = QImage(buf, w, h, w * 4, QImage.Format.Format_ARGB32)
            return img.copy()  # buf GC 전에 복사

        except Exception as exc:
            logger.debug("비디오 썸네일 추출 실패 (%s): %s", path, exc)
            return None

    @staticmethod
    def _make_placeholder(w: int, h: int) -> QImage:
        """썸네일 추출 실패 시 회색 플레이 아이콘 플레이스홀더."""
        from PyQt6.QtGui import QPainter, QPainterPath
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
    """썸네일 셀. 마우스 오버 시 1.5배 확대 팝업을 표시한다.

    팝업은 popup_parent(사이드바 프레임)의 직접 자식으로 생성되어 레이아웃 위에 표시됩니다.
    """

    _EXPAND = 1.5
    _EXPAND_MS = 150
    _COLLAPSE_MS = 120
    _COLLAPSE_DELAY_MS = 50   # leaveEvent 후 축소를 지연(경계 근처 깜빡임 방지)

    def __init__(
        self,
        base_w: int,
        base_h: int,
        popup_parent: QWidget,
        on_click: Optional[Callable[[], None]] = None,
        tooltip: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._base_w = base_w
        self._base_h = base_h
        self._exp_w = int(base_w * self._EXPAND)
        self._exp_h = int(base_h * self._EXPAND)
        self._popup_parent = popup_parent
        self._on_click = on_click
        self._hi_pixmap: Optional[QPixmap] = None
        self._popup: Optional[QLabel] = None
        self._expand_anim: Optional[QPropertyAnimation] = None
        self._collapse_anim: Optional[QPropertyAnimation] = None

        # 지연 축소 타이머
        self._collapse_timer = QTimer(self)
        self._collapse_timer.setSingleShot(True)
        self._collapse_timer.setInterval(self._COLLAPSE_DELAY_MS)
        self._collapse_timer.timeout.connect(self._collapse_popup)

        self.setFixedSize(base_w, base_h)
        self.setToolTip(tooltip)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("""
            QLabel {
                background: rgba(255,255,255,6);
                border: 1px solid rgba(255,255,255,15);
                border-radius: 3px;
            }
        """)

    def set_hi_pixmap(self, pixmap: QPixmap) -> None:
        """고화질 픽셀맵을 저장하고 기본 크기로 표시합니다."""
        self._hi_pixmap = pixmap
        lo = pixmap.scaled(
            self._base_w, self._base_h,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        x_off = max(0, (lo.width() - self._base_w) // 2)
        y_off = max(0, (lo.height() - self._base_h) // 2)
        self.setPixmap(lo.copy(x_off, y_off, self._base_w, self._base_h))

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self._collapse_timer.stop()

        # 진행 중인 축소 애니메이션과 팝업 정리
        self._stop_anim(attr="_collapse_anim")
        if self._popup is not None:
            try:
                self._popup.deleteLater()
            except RuntimeError:
                pass
            self._popup = None

        if self._hi_pixmap is None:
            return

        pos = self.mapTo(self._popup_parent, QPoint(0, 0))
        cx = pos.x() + self._base_w // 2
        cy = pos.y() + self._base_h // 2

        start_rect = QRect(pos.x(), pos.y(), self._base_w, self._base_h)
        end_rect = QRect(
            cx - self._exp_w // 2,
            cy - self._exp_h // 2,
            self._exp_w, self._exp_h,
        )

        pix = self._hi_pixmap.scaled(
            self._exp_w, self._exp_h,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        x_off = max(0, (pix.width() - self._exp_w) // 2)
        y_off = max(0, (pix.height() - self._exp_h) // 2)
        pix = pix.copy(x_off, y_off, self._exp_w, self._exp_h)

        popup = QLabel(self._popup_parent)
        popup.setAlignment(Qt.AlignmentFlag.AlignCenter)
        popup.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        popup.setStyleSheet("QLabel { background: rgba(12,12,16,220); border-radius: 4px; }")
        popup.setPixmap(pix)
        popup.setGeometry(start_rect)
        popup.raise_()
        popup.show()
        self._popup = popup

        self._stop_anim(attr="_expand_anim")
        anim = QPropertyAnimation(popup, b"geometry", self)  # self를 parent로 — 수명 관리
        anim.setDuration(self._EXPAND_MS)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.setStartValue(start_rect)
        anim.setEndValue(end_rect)
        anim.start()
        self._expand_anim = anim

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self._collapse_timer.start()

    def _collapse_popup(self) -> None:
        self._stop_anim(attr="_expand_anim")

        if self._popup is None:
            return

        pos = self.mapTo(self._popup_parent, QPoint(0, 0))
        end_rect = QRect(pos.x(), pos.y(), self._base_w, self._base_h)

        anim = QPropertyAnimation(self._popup, b"geometry", self)  # self가 parent
        anim.setDuration(self._COLLAPSE_MS)
        anim.setEasingCurve(QEasingCurve.Type.InCubic)
        anim.setEndValue(end_rect)
        anim.finished.connect(self._on_collapse_done)
        anim.start()
        self._collapse_anim = anim

    def _on_collapse_done(self) -> None:
        if self._popup is not None:
            try:
                self._popup.deleteLater()
            except RuntimeError:
                pass
            self._popup = None
        if self._collapse_anim is not None:
            try:
                self._collapse_anim.deleteLater()
            except RuntimeError:
                pass
            self._collapse_anim = None

    def _stop_anim(self, attr: str) -> None:
        anim = getattr(self, attr, None)
        if anim is not None:
            try:
                anim.stop()
                anim.deleteLater()
            except RuntimeError:
                pass
            setattr(self, attr, None)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._on_click:
            self._on_click()
        super().mousePressEvent(event)


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
        stop_recording: Optional[Callable[[], None]] = None,
        reconnect_recording: Optional[Callable[[], None]] = None,
        get_recording_error: Optional[Callable[[], str]] = None,
        get_recording_elapsed: Optional[Callable[[], int]] = None,
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
        self._stop_recording_callback = stop_recording
        self._reconnect_recording = reconnect_recording
        self._get_recording_error = get_recording_error
        self._get_recording_elapsed = get_recording_elapsed
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
        self._save_pool = QThreadPool(self)
        self._save_pool.setMaxThreadCount(1)

        # 스크린샷 썸네일 디코딩용 스레드풀
        self._thumb_pool = QThreadPool(self)
        self._thumb_pool.setMaxThreadCount(2)
        self._thumb_signals = _ThumbnailLoadSignals(self)
        self._thumb_signals.loaded.connect(self._apply_thumbnail_result)

        # 녹화 썸네일 디코딩용 스레드풀 (별도)
        self._rec_thumb_pool = QThreadPool(self)
        self._rec_thumb_pool.setMaxThreadCount(2)
        self._rec_thumb_signals = _ThumbnailLoadSignals(self)
        self._rec_thumb_signals.loaded.connect(self._apply_rec_thumbnail_result)

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
        self._refresh_recording_thumbnails()

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

        # 헤더 행: 제목 + [지금 녹화] 버튼
        header = QHBoxLayout()
        title = QLabel("녹화")
        title.setStyleSheet(
            "color: rgba(150,170,210,160); font-size: 10px; letter-spacing: 1px;"
        )
        self._rec_start_btn = QPushButton("지금 녹화")
        self._rec_start_btn.setFixedHeight(28)
        self._rec_start_btn.setStyleSheet("""
            QPushButton {
                background: rgba(180,40,40,160);
                color: rgba(255,200,200,220);
                border: 1px solid rgba(220,60,60,120);
                border-radius: 4px;
                font-size: 11px;
            }
            QPushButton:hover { background: rgba(220,50,50,200); color: white; }
            QPushButton:pressed { background: rgba(140,20,20,220); }
        """)
        self._rec_start_btn.clicked.connect(self._on_rec_start_clicked)
        self._rec_start_btn.hide()
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self._rec_start_btn)
        layout.addLayout(header)

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

        # 녹화 썸네일 그리드
        self._rec_thumb_grid_container = QWidget()
        self._rec_thumb_grid_container.setStyleSheet("background: transparent;")
        self._rec_thumb_grid_layout = QGridLayout(self._rec_thumb_grid_container)
        self._rec_thumb_grid_layout.setSpacing(3)
        self._rec_thumb_grid_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._rec_thumb_grid_container)

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

    def set_recording_elapsed_provider(self, fn: Optional[Callable[[], int]]) -> None:
        """현재 녹화 경과 시간을 초 단위로 제공하는 콜백을 등록합니다."""
        self._get_recording_elapsed = fn

    def set_on_start_recording(self, fn: Optional[Callable[[], None]]) -> None:
        """[지금 녹화] 버튼 클릭 시 호출될 콜백을 등록합니다."""
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
        if state == "recording":
            if self._get_recording_elapsed:
                elapsed = max(0, int(self._get_recording_elapsed()))
                self._rec_elapsed_sec = elapsed
            mins, secs = divmod(elapsed, 60)
            hrs, mins = divmod(mins, 60)
            self._rec_status_label.setText(f"● REC  {hrs:02d}:{mins:02d}:{secs:02d}")
            self._rec_status_label.setStyleSheet("color: #e05555; font-size: 12px;")
            self._rec_stop_btn.show()
            self._rec_start_btn.hide()
            self._rec_connect_btn.hide()
        elif state == "idle":
            self._rec_status_label.setText("● OBS 대기 중")
            self._rec_status_label.setStyleSheet("color: #5aaa5a; font-size: 12px;")
            self._rec_stop_btn.hide()
            self._rec_start_btn.show()
            self._rec_connect_btn.hide()
        elif state == "connecting":
            self._rec_status_label.setText("○ OBS 연결 중...")
            self._rec_status_label.setStyleSheet("color: #aaa850; font-size: 12px;")
            self._rec_stop_btn.hide()
            self._rec_start_btn.hide()
            self._rec_connect_btn.hide()
        else:  # obs_offline
            self._rec_status_label.setText("○ OBS 오프라인")
            self._rec_status_label.setStyleSheet("color: #888; font-size: 12px;")
            self._rec_stop_btn.hide()
            self._rec_start_btn.hide()
            self._rec_connect_btn.show()
            # 마지막 연결 실패 이유를 툴팁으로 표시
            err = self._get_recording_error() if self._get_recording_error else ""
            self._rec_status_label.setToolTip(err if err else "")
            self._rec_connect_btn.setToolTip(err if err else "")

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
        """[지금 녹화] 버튼 클릭 — 카운트다운 콜백을 호출합니다."""
        if self._start_recording_callback:
            self._start_recording_callback()

    def _refresh_recording_section(self) -> None:
        """recording_enabled 설정에 따라 섹션 show/hide."""
        gs = getattr(self._data_manager, 'global_settings', None)
        enabled = getattr(gs, 'recording_enabled', False) if gs else False
        self._recording_section.setVisible(enabled)
        self._update_rec_ui()

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
        self._thumb_request_id += 1
        request_id = self._thumb_request_id
        self._thumb_buttons = {}

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
            cell = self._make_thumb_cell(fp, request_id)
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

        # 현재 표시 목록에 없는 캐시 항목 제거
        shown_paths = {str(fp) for fp in shown}
        self._thumb_cache = {k: v for k, v in self._thumb_cache.items() if k in shown_paths}

    def _make_thumb_cell(self, filepath, request_id: int) -> _HoverThumbCell:
        """썸네일 셀 _HoverThumbCell을 반환합니다."""
        path_str = str(filepath)
        _fp = filepath

        def _open() -> None:
            os.startfile(path_str)

        cell = _HoverThumbCell(
            _THUMB_W, _THUMB_H,
            popup_parent=self._frame,
            on_click=_open,
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

    @pyqtSlot(int, str, object)
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
        from PyQt6.QtCore import QMetaObject, Qt
        QMetaObject.invokeMethod(
            self, "_refresh_screenshot_thumbnails",
            Qt.ConnectionType.QueuedConnection,
        )

    @pyqtSlot()
    def _refresh_recording_thumbnails(self) -> None:
        """녹화 썸네일 그리드를 최신 MP4 파일로 갱신합니다."""
        self._rec_thumb_request_id += 1
        request_id = self._rec_thumb_request_id
        self._rec_thumb_buttons = {}

        # 그리드 초기화
        while self._rec_thumb_grid_layout.count():
            item = self._rec_thumb_grid_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        output_dir = self._recording_output_dir
        if not output_dir:
            return

        rec_path = Path(output_dir)
        if not rec_path.exists():
            return

        # 최신 MP4 파일 목록
        files = sorted(
            [f for f in rec_path.iterdir() if f.suffix.lower() == '.mp4' and f.is_file()],
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )

        max_shown = _THUMB_MAX_CELLS - 1
        shown = files[:max_shown]
        remaining = max(0, len(files) - max_shown)

        # 썸네일 셀 추가
        for idx, fp in enumerate(shown):
            row, col = divmod(idx, _THUMB_COLS)
            cell = self._make_rec_thumb_cell(fp, request_id)
            self._rec_thumb_grid_layout.addWidget(cell, row, col)

        # 폴더 버튼 (마지막 셀)
        folder_label = f"+{remaining}" if remaining > 0 else "\U0001F4C2"
        folder_btn = QPushButton(folder_label)
        folder_btn.setFixedSize(_THUMB_W, _THUMB_H)
        folder_btn.setToolTip("녹화 폴더 열기")
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
        _dir = output_dir

        def _open_rec_folder(d: str = _dir) -> None:
            if Path(d).exists():
                os.startfile(d)

        folder_btn.clicked.connect(lambda _checked=False: _open_rec_folder())
        next_idx = len(shown)
        row, col = divmod(next_idx, _THUMB_COLS)
        self._rec_thumb_grid_layout.addWidget(folder_btn, row, col)

        # 현재 표시 목록에 없는 캐시 항목 제거
        rec_shown_paths = {str(fp) for fp in shown}
        self._rec_thumb_cache = {k: v for k, v in self._rec_thumb_cache.items() if k in rec_shown_paths}

    def _make_rec_thumb_cell(self, filepath, request_id: int) -> _HoverThumbCell:
        """녹화 썸네일 셀 _HoverThumbCell을 반환합니다."""
        path_str = str(filepath)

        def _open() -> None:
            os.startfile(path_str)

        cell = _HoverThumbCell(
            _THUMB_W, _THUMB_H,
            popup_parent=self._frame,
            on_click=_open,
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

    @pyqtSlot(int, str, object)
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
