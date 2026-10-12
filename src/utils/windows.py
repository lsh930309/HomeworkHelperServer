# windows_utils.py
import os
import logging
import ctypes
import ctypes.wintypes

logger = logging.getLogger(__name__)

_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_CAPTION_COLOR = 35
_DWMWA_TEXT_COLOR = 36
_DWMWA_EXTENDED_FRAME_BOUNDS = 9
_MONITOR_DEFAULTTONEAREST = 2
_SWP_FRAME_MOVE_FLAGS = 0x0001 | 0x0004 | 0x0010


class _MonitorInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.wintypes.DWORD),
        ("rcMonitor", ctypes.wintypes.RECT),
        ("rcWork", ctypes.wintypes.RECT),
        ("dwFlags", ctypes.wintypes.DWORD),
    ]


def _configure_window_geometry_api(user32) -> None:
    user32.GetMonitorInfoW.argtypes = [ctypes.wintypes.HMONITOR, ctypes.POINTER(_MonitorInfo)]
    user32.GetMonitorInfoW.restype = ctypes.wintypes.BOOL
    user32.GetWindowRect.argtypes = [ctypes.wintypes.HWND, ctypes.POINTER(ctypes.wintypes.RECT)]
    user32.GetWindowRect.restype = ctypes.wintypes.BOOL
    user32.SetWindowPos.argtypes = [
        ctypes.wintypes.HWND,
        ctypes.wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.wintypes.UINT,
    ]
    user32.SetWindowPos.restype = ctypes.wintypes.BOOL


def _get_monitor_work_area(user32, monitor):
    monitor_info = _MonitorInfo()
    monitor_info.cbSize = ctypes.sizeof(_MonitorInfo)
    if not user32.GetMonitorInfoW(monitor, ctypes.byref(monitor_info)):
        return None
    work = monitor_info.rcWork
    return work.left, work.top, work.right, work.bottom


def _get_window_frame_rects(user32, hwnd):
    """Win32 외곽 RECT와 실제로 보이는 DWM 프레임 RECT를 함께 반환합니다."""
    native_hwnd = ctypes.wintypes.HWND(hwnd)
    outer = ctypes.wintypes.RECT()
    if not user32.GetWindowRect(native_hwnd, ctypes.byref(outer)):
        return None

    visible = ctypes.wintypes.RECT(outer.left, outer.top, outer.right, outer.bottom)
    try:
        dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
        dwmapi.DwmGetWindowAttribute.argtypes = [
            ctypes.wintypes.HWND,
            ctypes.wintypes.DWORD,
            ctypes.c_void_p,
            ctypes.wintypes.DWORD,
        ]
        dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long
        candidate = ctypes.wintypes.RECT()
        result = dwmapi.DwmGetWindowAttribute(
            native_hwnd,
            _DWMWA_EXTENDED_FRAME_BOUNDS,
            ctypes.byref(candidate),
            ctypes.sizeof(candidate),
        )
        if result == 0 and candidate.right > candidate.left and candidate.bottom > candidate.top:
            visible = candidate
    except (AttributeError, OSError):
        pass
    return outer, visible


def snap_rect_to_work_area(
    rect: tuple[int, int, int, int],
    work_area: tuple[int, int, int, int],
    threshold: int,
) -> tuple[int, int, int, int]:
    """창 크기를 유지한 채 가까운 작업 영역 경계에 사각형을 붙입니다."""
    left, top, right, bottom = rect
    work_left, work_top, work_right, work_bottom = work_area
    width = right - left
    height = bottom - top
    distance = max(0, int(threshold))

    if abs(left - work_left) <= distance:
        left, right = work_left, work_left + width
    elif abs(right - work_right) <= distance:
        left, right = work_right - width, work_right

    if abs(top - work_top) <= distance:
        top, bottom = work_top, work_top + height
    elif abs(bottom - work_bottom) <= distance:
        top, bottom = work_bottom - height, work_bottom

    return left, top, right, bottom


def snap_windows_window_to_work_area(hwnd: int, *, threshold_logical: int = 15) -> bool:
    """현재 창의 보이는 DWM 프레임을 가까운 모니터 작업 영역 경계에 붙입니다."""
    if not is_windows() or not hwnd:
        return False

    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        _configure_window_geometry_api(user32)
        user32.MonitorFromWindow.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.DWORD]
        user32.MonitorFromWindow.restype = ctypes.wintypes.HMONITOR
        native_hwnd = ctypes.wintypes.HWND(hwnd)
        monitor = user32.MonitorFromWindow(native_hwnd, _MONITOR_DEFAULTTONEAREST)
        if not monitor:
            return False
        work_area = _get_monitor_work_area(user32, monitor)
        frame_rects = _get_window_frame_rects(user32, hwnd)
        if work_area is None or frame_rects is None:
            return False
        outer, visible = frame_rects

        dpi = 96
        get_dpi_for_window = getattr(user32, "GetDpiForWindow", None)
        if get_dpi_for_window is not None:
            get_dpi_for_window.argtypes = [ctypes.wintypes.HWND]
            get_dpi_for_window.restype = ctypes.wintypes.UINT
            reported_dpi = int(get_dpi_for_window(ctypes.wintypes.HWND(hwnd)))
            if reported_dpi > 0:
                dpi = reported_dpi
        threshold = max(1, round(threshold_logical * dpi / 96))
        original = (visible.left, visible.top, visible.right, visible.bottom)
        snapped = snap_rect_to_work_area(
            original,
            work_area,
            threshold,
        )
        if snapped == original:
            return False
        left = outer.left + snapped[0] - visible.left
        top = outer.top + snapped[1] - visible.top
        return bool(user32.SetWindowPos(native_hwnd, None, left, top, 0, 0, _SWP_FRAME_MOVE_FLAGS))
    except Exception as exc:
        logger.debug("Windows 창 가시 프레임 자석 적용 실패: %s", exc)
        return False


def position_windows_window_bottom_right(hwnd: int, cursor_x: int, cursor_y: int) -> bool:
    """커서 모니터의 작업 영역 우하단에 보이는 DWM 프레임을 맞춥니다."""
    if not is_windows() or not hwnd:
        return False

    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        _configure_window_geometry_api(user32)
        user32.MonitorFromPoint.argtypes = [ctypes.wintypes.POINT, ctypes.wintypes.DWORD]
        user32.MonitorFromPoint.restype = ctypes.wintypes.HMONITOR

        monitor = user32.MonitorFromPoint(
            ctypes.wintypes.POINT(int(cursor_x), int(cursor_y)),
            _MONITOR_DEFAULTTONEAREST,
        )
        if not monitor:
            return False
        work_area = _get_monitor_work_area(user32, monitor)
        frame_rects = _get_window_frame_rects(user32, hwnd)
        if work_area is None or frame_rects is None:
            return False
        outer, visible = frame_rects
        left = outer.left + work_area[2] - visible.right
        top = outer.top + work_area[3] - visible.bottom
        return bool(user32.SetWindowPos(
            ctypes.wintypes.HWND(hwnd),
            None,
            left,
            top,
            0,
            0,
            _SWP_FRAME_MOVE_FLAGS,
        ))
    except Exception as exc:
        logger.debug("Windows 창 우하단 배치 실패: %s", exc)
        return False

def is_windows() -> bool:
    return os.name == 'nt'

def _to_colorref(rgb: tuple[int, int, int]) -> int:
    """(R, G, B)를 Windows COLORREF(0x00bbggrr) 정수로 변환합니다."""
    red, green, blue = (max(0, min(255, int(channel))) for channel in rgb)
    return red | (green << 8) | (blue << 16)


def apply_windows_title_bar_color(
    hwnd: int,
    *,
    caption_color: tuple[int, int, int],
    text_color: tuple[int, int, int],
    dark_mode: bool,
) -> bool:
    """표준 Windows 제목 표시줄 색상을 앱 팔레트와 맞춥니다.

    Windows 11의 DWM non-client 색상 API를 직접 사용하는 best-effort 기능입니다.
    지원되지 않는 Windows 버전/환경에서는 커스텀 타이틀바 같은 우회 구현 없이 즉시 실패합니다.

    Args:
        hwnd: 대상 최상위 창 핸들.
        caption_color: 제목 표시줄 배경 RGB.
        text_color: 제목 표시줄 텍스트 RGB.
        dark_mode: 어두운 제목 표시줄 모드 사용 여부.

    Returns:
        캡션 색상 지정 성공 여부.
    """
    if not is_windows() or not hwnd:
        return False

    try:
        dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)

        dark_value = ctypes.c_int(1 if dark_mode else 0)
        # 이 속성은 Windows 11에서 공식 지원되며, 구버전에서는 실패할 수 있습니다.
        dwmapi.DwmSetWindowAttribute(
            ctypes.wintypes.HWND(hwnd),
            ctypes.c_uint(_DWMWA_USE_IMMERSIVE_DARK_MODE),
            ctypes.byref(dark_value),
            ctypes.sizeof(dark_value),
        )

        caption_value = ctypes.c_uint(_to_colorref(caption_color))
        caption_result = dwmapi.DwmSetWindowAttribute(
            ctypes.wintypes.HWND(hwnd),
            ctypes.c_uint(_DWMWA_CAPTION_COLOR),
            ctypes.byref(caption_value),
            ctypes.sizeof(caption_value),
        )

        text_value = ctypes.c_uint(_to_colorref(text_color))
        dwmapi.DwmSetWindowAttribute(
            ctypes.wintypes.HWND(hwnd),
            ctypes.c_uint(_DWMWA_TEXT_COLOR),
            ctypes.byref(text_value),
            ctypes.sizeof(text_value),
        )

        return caption_result == 0
    except Exception as e:
        logger.debug("Windows 제목 표시줄 색상 적용 실패: %s", e)
        return False
