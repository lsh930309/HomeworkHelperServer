"""비활성 사이드바의 고정 Acrylic 경계. Windows accent 호출은 비공개 확장이다.

Windows 11 Background Acrylic의 비활성 단색 전환과 Qt의 이중 tint를 피한다.
OS별 선택기·재시도 없이 기존 accent Acrylic을 지원 빌드에서 한 번 요청한다.
"""
import ctypes
import ctypes.wintypes
import logging
import sys

logger = logging.getLogger(__name__)

ACRYLIC_TINT = (8, 12, 19, 153)  # RGBA: 배경만 60% tint, 글자·아이콘 opacity는 1
_WIN10_1809 = 17763


def _get_windows_build() -> int:
    if sys.platform != "win32":
        return 0
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion") as key:
            return int(winreg.QueryValueEx(key, "CurrentBuildNumber")[0])
    except OSError:
        return int(sys.getwindowsversion().build)


_WINDOWS_BUILD = _get_windows_build()


class _ACCENT_POLICY(ctypes.Structure):
    _fields_ = [
        ("AccentState", ctypes.c_uint),
        ("AccentFlags", ctypes.c_uint),
        ("GradientColor", ctypes.c_uint),
        ("AnimationId", ctypes.c_uint),
    ]


class _WINDOWCOMPOSITIONATTRIBDATA(ctypes.Structure):
    _fields_ = [
        ("Attribute", ctypes.c_uint),
        ("pData", ctypes.c_void_p),
        ("cbData", ctypes.c_size_t),
    ]


def apply_blur_effect(hwnd: int) -> bool:
    """현재 창의 포커스를 바꾸지 않고 기존 accent Acrylic을 적용한다."""
    if sys.platform != "win32" or not hwnd or _WINDOWS_BUILD < _WIN10_1809:
        return False
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.SetWindowCompositionAttribute.argtypes = [
            ctypes.wintypes.HWND, ctypes.POINTER(_WINDOWCOMPOSITIONATTRIBDATA),
        ]
        user32.SetWindowCompositionAttribute.restype = ctypes.wintypes.BOOL
        red, green, blue, alpha = ACRYLIC_TINT
        accent = _ACCENT_POLICY(
            4, 0, (alpha << 24) | (blue << 16) | (green << 8) | red, 0,
        )  # ACCENT_ENABLE_ACRYLICBLURBEHIND; GradientColor는 ABGR
        data = _WINDOWCOMPOSITIONATTRIBDATA(
            19, ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p), ctypes.sizeof(accent),
        )  # WCA_ACCENT_POLICY
        result = user32.SetWindowCompositionAttribute(ctypes.wintypes.HWND(hwnd), ctypes.byref(data))
        if not result:
            logger.warning("사이드바 accent Acrylic 호출 실패: hwnd=%s", hwnd)
        return bool(result)
    except Exception:
        logger.warning("사이드바 accent Acrylic 적용 예외: hwnd=%s", hwnd, exc_info=True)
        return False
