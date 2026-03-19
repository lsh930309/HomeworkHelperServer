"""스크린샷 캡처 — pywin32 GDI BitBlt 기반, mss/Pillow 선택적 사용.

우선순위:
  1. mss      — pip install mss 시 사용 (가장 빠름, GPU 렌더링 포함)
  2. pywin32  — 기본 내장 (GDI BitBlt, Pillow 있으면 PNG / 없으면 BMP)
"""
import ctypes
import datetime
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_SAVE_DIR = Path.home() / "Pictures" / "GameCaptures"


def take_screenshot(save_dir: Optional[str] = None) -> Optional[str]:
    """현재 화면을 캡처해 파일로 저장합니다.

    캡처 직전 마우스 커서를 숨기고, 완료 후 복원합니다.

    Returns:
        저장된 파일의 절대 경로 문자열. 실패 시 None.
    """
    save_path = _build_save_path(save_dir)
    save_path.parent.mkdir(parents=True, exist_ok=True)

    # 커서 숨김 → 캡처 → 커서 복원
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


# ──────────────────────────────────────────────────────────────
# 내부 헬퍼
# ──────────────────────────────────────────────────────────────

def _build_save_path(save_dir: Optional[str]) -> Path:
    base = Path(save_dir) if save_dir else _DEFAULT_SAVE_DIR
    ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    return base / f"capture_{ts}.png"


def _try_mss(save_path: Path) -> Optional[str]:
    """mss 라이브러리로 캡처. 미설치 시 None 반환."""
    try:
        import mss
        import mss.tools
        with mss.mss() as sct:
            img = sct.grab(sct.monitors[0])   # 전체 가상 스크린
            mss.tools.to_png(img.rgb, img.size, output=str(save_path))
        return str(save_path)
    except ImportError:
        return None
    except Exception as exc:
        logger.debug("mss 캡처 실패: %s", exc)
        return None


def _try_gdi(save_path: Path) -> Optional[str]:
    """pywin32 GDI BitBlt로 캡처.

    Pillow 설치 시 PNG, 미설치 시 BMP 로 저장합니다.
    """
    try:
        import win32api
        import win32con
        import win32gui
        import win32ui

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
            # Pillow 미설치 → BMP로 저장
            bmp_path = save_path.with_suffix(".bmp")
            bmp.SaveBitmapFile(mem_dc, str(bmp_path))
            logger.warning("Pillow 미설치 — BMP 저장: %s", bmp_path)
            result = str(bmp_path)
        finally:
            win32gui.DeleteObject(bmp.GetHandle())
            mem_dc.DeleteDC()
            mfc_dc.DeleteDC()
            win32gui.ReleaseDC(hwnd, hdc_src)

        return result

    except Exception as exc:
        logger.debug("GDI 캡처 실패: %s", exc)
        return None


def _save_as_png(bmp, width: int, height: int, save_path: Path) -> str:
    """win32ui Bitmap → Pillow Image → PNG 저장. Pillow 없으면 ImportError."""
    from PIL import Image  # noqa: PLC0415
    raw = bmp.GetBitmapBits(True)
    img = Image.frombuffer("RGB", (width, height), raw, "raw", "BGRX", 0, 1)
    img.save(str(save_path), "PNG")
    return str(save_path)
