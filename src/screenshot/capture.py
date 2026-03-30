"""스크린샷 캡처 — mss 우선, pywin32 GDI BitBlt 폴백.

우선순위:
  1. mss      — pip install mss (가장 빠름, GPU 렌더링 포함)
  2. pywin32  — 기본 내장 (GDI BitBlt, Pillow 있으면 PNG / 없으면 BMP)
"""
import ctypes
import ctypes.wintypes as wintypes
import datetime
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_SAVE_DIR = Path.home() / "Pictures" / "GameCaptures"


# ──────────────────────────────────────────────────────────────
# 공개 API
# ──────────────────────────────────────────────────────────────

def take_screenshot(save_dir: Optional[str] = None, game_name: str = "") -> Optional[str]:
    """현재 전체 화면을 캡처해 파일로 저장합니다."""
    save_path = _build_save_path(save_dir, game_name)
    save_path.parent.mkdir(parents=True, exist_ok=True)

    ctypes.windll.user32.ShowCursor(False)
    try:
        result = _try_mss(save_path) or _try_gdi(save_path)
    finally:
        ctypes.windll.user32.ShowCursor(True)

    if result:
        logger.info("스크린샷 저장: %s", result)
        return result
    logger.error("스크린샷 캡처 실패 — mss 및 GDI 모두 실패")
    return None


def take_screenshot_window(hwnd: int, save_dir: Optional[str] = None, game_name: str = "") -> Optional[str]:
    """지정 창의 클라이언트 영역(렌더링 영역)만 캡처합니다.

    창이 최소화되어 있거나 클라이언트 크기가 0이면 전체 화면 폴백을 사용합니다.
    """
    region = _get_client_region(hwnd)
    if region is None:
        logger.debug("take_screenshot_window: 클라이언트 영역 획득 실패 → 전체 화면 폴백")
        return take_screenshot(save_dir=save_dir, game_name=game_name)

    x, y, w, h = region
    if w <= 0 or h <= 0:
        return take_screenshot(save_dir=save_dir, game_name=game_name)

    save_path = _build_save_path(save_dir, game_name)
    save_path.parent.mkdir(parents=True, exist_ok=True)

    ctypes.windll.user32.ShowCursor(False)
    try:
        result = _try_mss_region(save_path, x, y, w, h) or _try_gdi_region(save_path, x, y, w, h)
    finally:
        ctypes.windll.user32.ShowCursor(True)

    if result:
        logger.info("창 스크린샷 저장: %s (hwnd=%d, %dx%d)", result, hwnd, w, h)
        return result
    logger.error("창 스크린샷 캡처 실패")
    return None


# ──────────────────────────────────────────────────────────────
# 내부 헬퍼 — 경로/영역
# ──────────────────────────────────────────────────────────────

def _sanitize_filename(name: str) -> str:
    """Windows 파일명 금지 문자(\\/:*?"<>|)를 제거합니다."""
    import re
    sanitized = re.sub(r'[\\/:*?"<>|]', '_', name).strip()
    return sanitized[:60] if sanitized else "capture"


def _build_save_path(save_dir: Optional[str], game_name: str = "") -> Path:
    base = Path(save_dir) if save_dir else _DEFAULT_SAVE_DIR
    now = datetime.datetime.now()
    hour_12 = now.hour % 12 or 12
    ampm = "오전" if now.hour < 12 else "오후"
    time_str = f"{hour_12}_{now.minute:02d}_{now.second:02d}"
    date_str = now.strftime("%Y-%m-%d")
    safe_name = _sanitize_filename(game_name) if game_name.strip() else "capture"
    return base / f"{safe_name}_{date_str} {ampm} {time_str}.png"


def _get_client_region(hwnd: int) -> Optional[tuple]:
    """(x, y, width, height) 화면 좌표로 반환. 실패 시 None."""
    try:
        rect = wintypes.RECT()
        if not ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(rect)):
            return None
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        if w <= 0 or h <= 0:
            return None
        pt = wintypes.POINT(0, 0)
        ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(pt))
        return (pt.x, pt.y, w, h)
    except Exception as exc:
        logger.debug("_get_client_region 실패: %s", exc)
        return None


# ──────────────────────────────────────────────────────────────
# 내부 헬퍼 — 전체 화면 캡처
# ──────────────────────────────────────────────────────────────

def _try_mss(save_path: Path) -> Optional[str]:
    try:
        import mss
        import mss.tools
        with mss.mss() as sct:
            img = sct.grab(sct.monitors[0])
            mss.tools.to_png(img.rgb, img.size, output=str(save_path))
        return str(save_path)
    except ImportError:
        return None
    except Exception as exc:
        logger.debug("mss 전체화면 캡처 실패: %s", exc)
        return None


def _try_gdi(save_path: Path) -> Optional[str]:
    try:
        import win32api, win32con, win32gui, win32ui
        hwnd = win32gui.GetDesktopWindow()
        w = win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN)
        h = win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN)
        x = win32api.GetSystemMetrics(win32con.SM_XVIRTUALSCREEN)
        y = win32api.GetSystemMetrics(win32con.SM_YVIRTUALSCREEN)
        hdc_src = win32gui.GetWindowDC(hwnd)
        mfc_dc  = win32ui.CreateDCFromHandle(hdc_src)
        mem_dc  = mfc_dc.CreateCompatibleDC()
        bmp     = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(mfc_dc, w, h)
        mem_dc.SelectObject(bmp)
        mem_dc.BitBlt((0, 0), (w, h), mfc_dc, (x, y), win32con.SRCCOPY)
        try:
            result = _save_as_png(bmp, w, h, save_path)
        except ImportError:
            bmp_path = save_path.with_suffix(".bmp")
            bmp.SaveBitmapFile(mem_dc, str(bmp_path))
            result = str(bmp_path)
        finally:
            win32gui.DeleteObject(bmp.GetHandle())
            mem_dc.DeleteDC()
            mfc_dc.DeleteDC()
            win32gui.ReleaseDC(hwnd, hdc_src)
        return result
    except Exception as exc:
        logger.debug("GDI 전체화면 캡처 실패: %s", exc)
        return None


# ──────────────────────────────────────────────────────────────
# 내부 헬퍼 — 영역 캡처
# ──────────────────────────────────────────────────────────────

def _try_mss_region(save_path: Path, x: int, y: int, w: int, h: int) -> Optional[str]:
    try:
        import mss
        import mss.tools
        with mss.mss() as sct:
            monitor = {"top": y, "left": x, "width": w, "height": h}
            img = sct.grab(monitor)
            mss.tools.to_png(img.rgb, img.size, output=str(save_path))
        return str(save_path)
    except ImportError:
        return None
    except Exception as exc:
        logger.debug("mss 영역 캡처 실패: %s", exc)
        return None


def _try_gdi_region(save_path: Path, x: int, y: int, w: int, h: int) -> Optional[str]:
    try:
        import win32gui, win32ui, win32con
        hwnd = win32gui.GetDesktopWindow()
        hdc_src = win32gui.GetWindowDC(hwnd)
        mfc_dc  = win32ui.CreateDCFromHandle(hdc_src)
        mem_dc  = mfc_dc.CreateCompatibleDC()
        bmp     = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(mfc_dc, w, h)
        mem_dc.SelectObject(bmp)
        mem_dc.BitBlt((0, 0), (w, h), mfc_dc, (x, y), win32con.SRCCOPY)
        try:
            result = _save_as_png(bmp, w, h, save_path)
        except ImportError:
            bmp_path = save_path.with_suffix(".bmp")
            bmp.SaveBitmapFile(mem_dc, str(bmp_path))
            result = str(bmp_path)
        finally:
            win32gui.DeleteObject(bmp.GetHandle())
            mem_dc.DeleteDC()
            mfc_dc.DeleteDC()
            win32gui.ReleaseDC(hwnd, hdc_src)
        return result
    except Exception as exc:
        logger.debug("GDI 영역 캡처 실패: %s", exc)
        return None


def _save_as_png(bmp, width: int, height: int, save_path: Path) -> str:
    from PIL import Image
    raw = bmp.GetBitmapBits(True)
    img = Image.frombuffer("RGB", (width, height), raw, "raw", "BGRX", 0, 1)
    img.save(str(save_path), "PNG")
    return str(save_path)
