"""Windows DWM Acrylic/Mica 효과 ctypes 래퍼.

Windows 빌드 버전에 따라 적용 가능한 효과가 다릅니다:
- Windows 11 (22000+): Mica, Acrylic (DWM Backdrop API)
- Windows 10 (17763+): Acrylic (SetWindowCompositionAttribute)
- 그 외: 효과 없음 (반투명 배경만 적용)
"""
import ctypes
import ctypes.wintypes
import logging
import sys

logger = logging.getLogger(__name__)

# Windows 빌드 버전 상수
_WIN11_BUILD = 22000   # Windows 11 최초 빌드
_WIN10_1809  = 17763   # Acrylic 지원 최초 빌드 (RS5)


def _get_windows_build() -> int:
    """현재 Windows 빌드 번호를 반환합니다. Windows 이외 플랫폼에서는 0을 반환합니다."""
    if sys.platform != "win32":
        return 0
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
        )
        build_str, _ = winreg.QueryValueEx(key, "CurrentBuildNumber")
        winreg.CloseKey(key)
        return int(build_str)
    except Exception:
        # sys.getwindowsversion() 폴백
        try:
            ver = sys.getwindowsversion()
            return ver.build
        except Exception:
            return 0


_WINDOWS_BUILD = _get_windows_build()


def apply_blur_effect(hwnd: int, effect: str = "acrylic") -> bool:
    """창 핸들(hwnd)에 블러/반투명 효과를 적용합니다.

    Args:
        hwnd: 대상 창의 Win32 핸들.
        effect: "acrylic" | "mica" | "none"

    Returns:
        적용 성공 여부.
    """
    if sys.platform != "win32" or hwnd == 0:
        return False

    if effect == "none":
        return True

    try:
        if _WINDOWS_BUILD >= _WIN11_BUILD:
            return _apply_dwm_backdrop(hwnd, effect)
        elif _WINDOWS_BUILD >= _WIN10_1809:
            return _apply_acrylic_win10(hwnd)
        else:
            return False
    except Exception as e:
        logger.debug("블러 효과 적용 실패 (hwnd=%s, effect=%s): %s", hwnd, effect, e)
        return False


# ---------------------------------------------------------------------------
# Windows 11 — DwmSetWindowAttribute (DWMWA_SYSTEMBACKDROP_TYPE)
# ---------------------------------------------------------------------------
_DWMWA_SYSTEMBACKDROP_TYPE = 38
_DWMSBT_NONE    = 1
_DWMSBT_MICA    = 2
_DWMSBT_ACRYLIC = 3
_DWMSBT_TABBED  = 4  # Mica Alt


def _apply_dwm_backdrop(hwnd: int, effect: str) -> bool:
    """Windows 11 이상에서 DWM 백드롭 효과를 적용합니다."""
    try:
        dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
        backdrop_type = _DWMSBT_ACRYLIC if effect != "mica" else _DWMSBT_MICA
        value = ctypes.c_int(backdrop_type)
        result = dwmapi.DwmSetWindowAttribute(
            ctypes.wintypes.HWND(hwnd),
            ctypes.c_uint(_DWMWA_SYSTEMBACKDROP_TYPE),
            ctypes.byref(value),
            ctypes.sizeof(value),
        )
        if result != 0:
            logger.debug("DwmSetWindowAttribute 실패, HRESULT=0x%08x", result & 0xFFFFFFFF)
            return False
        return True
    except Exception as e:
        logger.debug("DWM 백드롭 적용 예외: %s", e)
        return False


# ---------------------------------------------------------------------------
# Windows 10 (1809+) — SetWindowCompositionAttribute Acrylic
# ---------------------------------------------------------------------------
_WCA_ACCENT_POLICY = 19

class _ACCENT_POLICY(ctypes.Structure):
    _fields_ = [
        ("AccentState",   ctypes.c_uint),
        ("AccentFlags",   ctypes.c_uint),
        ("GradientColor", ctypes.c_uint),
        ("AnimationId",   ctypes.c_uint),
    ]

class _WINDOWCOMPOSITIONATTRIBDATA(ctypes.Structure):
    _fields_ = [
        ("Attribute",  ctypes.c_uint),
        ("pData",      ctypes.c_void_p),
        ("cbData",     ctypes.c_size_t),
    ]

_ACCENT_ENABLE_ACRYLICBLURBEHIND = 4


def _apply_acrylic_win10(hwnd: int) -> bool:
    """Windows 10 1809+ 에서 Acrylic 블러를 SetWindowCompositionAttribute로 적용합니다."""
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        accent = _ACCENT_POLICY()
        accent.AccentState = _ACCENT_ENABLE_ACRYLICBLURBEHIND
        accent.AccentFlags = 0x20 | 0x40 | 0x80 | 0x100  # 사방 테두리 블러
        accent.GradientColor = 0xCC1A1A1A  # 어두운 반투명 배경 (알파 0xCC = ~80%)
        accent.AnimationId = 0

        data = _WINDOWCOMPOSITIONATTRIBDATA()
        data.Attribute = _WCA_ACCENT_POLICY
        data.pData = ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p)
        data.cbData = ctypes.sizeof(accent)

        result = user32.SetWindowCompositionAttribute(
            ctypes.wintypes.HWND(hwnd),
            ctypes.pointer(data),
        )
        return bool(result)
    except Exception as e:
        logger.debug("SetWindowCompositionAttribute 예외: %s", e)
        return False


def remove_blur_effect(hwnd: int) -> bool:
    """창에 적용된 블러 효과를 제거합니다."""
    if sys.platform != "win32" or hwnd == 0:
        return False
    try:
        if _WINDOWS_BUILD >= _WIN11_BUILD:
            dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
            value = ctypes.c_int(_DWMSBT_NONE)
            dwmapi.DwmSetWindowAttribute(
                ctypes.wintypes.HWND(hwnd),
                ctypes.c_uint(_DWMWA_SYSTEMBACKDROP_TYPE),
                ctypes.byref(value),
                ctypes.sizeof(value),
            )
        elif _WINDOWS_BUILD >= _WIN10_1809:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            accent = _ACCENT_POLICY()
            accent.AccentState = 0  # ACCENT_DISABLED
            data = _WINDOWCOMPOSITIONATTRIBDATA()
            data.Attribute = _WCA_ACCENT_POLICY
            data.pData = ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p)
            data.cbData = ctypes.sizeof(accent)
            user32.SetWindowCompositionAttribute(
                ctypes.wintypes.HWND(hwnd),
                ctypes.pointer(data),
            )
        return True
    except Exception as e:
        logger.debug("블러 효과 제거 예외: %s", e)
        return False
