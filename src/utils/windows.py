# windows_utils.py
import os
import logging
import ctypes
import ctypes.wintypes
from typing import Literal

logger = logging.getLogger(__name__)

_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_CAPTION_COLOR = 35
_DWMWA_TEXT_COLOR = 36
_DWMWA_EXTENDED_FRAME_BOUNDS = 9
_SWP_FRAME_MOVE_FLAGS = 0x0001 | 0x0004 | 0x0010
_WINDOW_SNAP_DISTANCE_LOGICAL = 15


def _configure_window_geometry_api(user32) -> None:
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


def get_visible_taskbar_work_area(monitor_origin: tuple[int, int], ignored_hwnd: int = 0):
    """대상 모니터의 물리 RECT와 실제 보이는 작업 표시줄을 뺀 RECT를 반환합니다.

    rcWork는 전체 화면에서도 예약 영역을 유지하므로 표면의 실제 창을 확인합니다.
    호출한 사이드바 자체는 가림 판정에서 제외해 높이 계산의 자기 의존을 없앱니다.
    OS 조회 실패는 None이며 호출자는 Qt 작업 영역을 사용합니다.
    """
    if not is_windows():
        return None
    try:
        import win32api
        import win32con
        import win32gui

        # Windows의 Qt는 모니터 크기만 DPI에 맞춰 축소하고 원점은 유지한다.
        # QScreen.name()은 제품명일 수 있어 Win32 장치명과 비교하지 않는다.
        handle = next((handle for handle, _dc, rect in win32api.EnumDisplayMonitors()
                       if rect[:2] == monitor_origin), None)
        if handle is None:
            return None
        info = win32api.GetMonitorInfo(handle)
        monitor = info["Monitor"]
        left, top, right, bottom = monitor
        work = [left, top, right, bottom]
        taskbars = []
        # 시작 메뉴 표시 중 Shell 창은 EnumWindows에서 누락될 수 있다.
        # 일반 앱 목록과 무관하게 대상 클래스를 직접 찾는다.
        for class_name in ("Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
            hwnd = 0
            while True:
                hwnd = win32gui.FindWindowEx(0, hwnd, class_name, None)
                if not hwnd:
                    break
                taskbars.append(hwnd)

        def contains(rect, point):
            return rect[0] <= point[0] < rect[2] and rect[1] <= point[1] < rect[3]

        def surface_at(point):
            hwnd = win32gui.WindowFromPoint(point)
            root = win32gui.GetAncestor(hwnd, 2) if hwnd else 0  # GA_ROOT
            if root != ignored_hwnd:
                return root
            # 사이드바를 움직이지 않고 그 아래 실제 가시 창을 확인한다.
            hwnd = win32gui.GetWindow(root, win32con.GW_HWNDNEXT)
            while hwnd:
                if (win32gui.IsWindowVisible(hwnd) and not win32gui.IsIconic(hwnd)
                        and not win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE) & win32con.WS_EX_TRANSPARENT
                        and contains(win32gui.GetWindowRect(hwnd), point)):
                    return hwnd
                hwnd = win32gui.GetWindow(hwnd, win32con.GW_HWNDNEXT)
            return 0

        for hwnd in taskbars:
            if not win32gui.IsWindowVisible(hwnd):
                continue
            rect = win32gui.GetWindowRect(hwnd)
            x1, y1 = max(left, rect[0]), max(top, rect[1])
            x2, y2 = min(right, rect[2]), min(bottom, rect[3])
            width, height = x2 - x1, y2 - y1
            if min(width, height) <= 2:  # 자동 숨김의 가장자리 감지 띠
                continue
            horizontal = width >= height
            points = [
                (x1 + int(width * fraction), (y1 + y2) // 2) if horizontal
                else ((x1 + x2) // 2, y1 + int(height * fraction))
                for fraction in (0.25, 0.5, 0.75)
            ]
            if not any(surface_at(point) == hwnd for point in points):
                continue
            if info["Work"] != monitor:
                # 표시 여부와 제외할 두께를 분리한다. Shell_TrayWnd의 외곽에는
                # 투명한 그림자 여백도 포함되므로 예약된 작업 영역이 정확하다.
                return monitor, info["Work"]
            if horizontal and y1 == top:
                work[1] = max(work[1], y2)
            elif horizontal and y2 == bottom:
                work[3] = min(work[3], y1)
            elif not horizontal and x1 == left:
                work[0] = max(work[0], x2)
            elif not horizontal and x2 == right:
                work[2] = min(work[2], x1)
        return monitor, tuple(work)
    except Exception as exc:
        logger.debug("Windows 작업 표시줄 가시 영역 조회 실패: %s", exc)
        return None


def place_window_rect_in_work_area(
    rect: tuple[int, int, int, int],
    work_area: tuple[int, int, int, int],
    *, placement: Literal["bottom_right", "snap", "contain"], threshold: int = _WINDOW_SNAP_DISTANCE_LOGICAL,
) -> tuple[int, int, int, int]:
    """표시·드래그·영역 보정의 서로 다른 의도를 현재 사각형만으로 계산한다."""
    left, top, right, bottom = rect
    work_left, work_top, work_right, work_bottom = work_area
    width, height = right - left, bottom - top
    if placement == "bottom_right":
        left, top = work_right - width, work_bottom - height
    elif placement == "contain":
        left = max(work_left, min(left, work_right - width))
        top = max(work_top, min(top, work_bottom - height))
    else:  # snap: 기존 15 논리 픽셀 자석. 멀리 있는 경계로는 이동하지 않는다.
        if abs(left - work_left) <= threshold:
            left = work_left
        elif abs(right - work_right) <= threshold:
            left = work_right - width
        if abs(top - work_top) <= threshold:
            top = work_top
        elif abs(bottom - work_bottom) <= threshold:
            top = work_bottom - height
    return left, top, left + width, top + height


def position_windows_window_in_work_area(
    hwnd: int, monitor_origin: tuple[int, int],
    *, placement: Literal["bottom_right", "snap", "contain"],
) -> bool:
    """가시 작업 영역과 DWM 프레임을 공유하고 의도에 필요한 이동만 적용한다."""
    if not is_windows() or not hwnd:
        return False
    try:
        native = get_visible_taskbar_work_area(monitor_origin, ignored_hwnd=hwnd)
        if native is None:
            return False
        _monitor, work_area = native
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        _configure_window_geometry_api(user32)
        frame_rects = _get_window_frame_rects(user32, hwnd)
        if frame_rects is None:
            return False
        outer, visible = frame_rects
        threshold = _WINDOW_SNAP_DISTANCE_LOGICAL
        if placement == "snap":
            user32.GetDpiForWindow.argtypes = [ctypes.wintypes.HWND]
            user32.GetDpiForWindow.restype = ctypes.wintypes.UINT
            dpi = int(user32.GetDpiForWindow(ctypes.wintypes.HWND(hwnd)))
            if not dpi:
                return False
            threshold = round(threshold * dpi / 96)
        original = (visible.left, visible.top, visible.right, visible.bottom)
        target = place_window_rect_in_work_area(original, work_area, placement=placement, threshold=threshold)
        dx, dy = target[0] - visible.left, target[1] - visible.top
        if dx == 0 and dy == 0:
            return True
        return bool(user32.SetWindowPos(
            ctypes.wintypes.HWND(hwnd), None,
            outer.left + dx, outer.top + dy, 0, 0, _SWP_FRAME_MOVE_FLAGS,
        ))
    except Exception as exc:
        logger.debug("Windows 창 작업 영역 배치 실패: 의도=%s 오류=%s", placement, exc)
        return False


def is_windows() -> bool:
    return os.name == 'nt'


def set_windows_taskbar_visible(hwnd: int, visible: bool) -> bool:
    """GUI 스레드에서 Shell 버튼만 조작하고 창의 네이티브 최소화 상태는 유지한다."""
    if not is_windows():
        return False
    try:
        import pythoncom
        from win32com.shell import shell
        taskbar = pythoncom.CoCreateInstance(
            shell.CLSID_TaskbarList, None, pythoncom.CLSCTX_INPROC_SERVER, shell.IID_ITaskbarList,
        )
        taskbar.HrInit()
        if visible:
            taskbar.AddTab(hwnd)
        else:
            taskbar.DeleteTab(hwnd)
        return True
    except Exception:
        logger.warning("Windows 작업 표시줄 버튼 변경 실패: 표시=%s", visible, exc_info=True)
        return False

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
