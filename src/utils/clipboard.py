"""클립보드 관련 유틸리티."""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import logging
import os
import struct
import time
from pathlib import Path

from PyQt6.QtCore import QBuffer, QIODevice, QMimeData, QUrl
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication

logger = logging.getLogger(__name__)

_GMEM_MOVEABLE = 0x0002
_CF_HDROP = 15
_CF_DIB = 8


def build_file_clipboard_mime_data(path: str | Path) -> QMimeData:
    """파일 복사용 QMimeData를 생성합니다.

    기본적으로 파일 URL을 넣어 Windows 탐색기에서 Ctrl+V로 붙여넣을 수 있게 합니다.
    이미지 파일인 경우에는 이미지 데이터도 함께 넣어 브라우저/메신저 입력창에서
    일반적인 이미지 붙여넣기 시나리오로 처리될 수 있도록 합니다.
    """

    file_path = Path(path)
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(file_path))])

    image = QImage(str(file_path))
    if image.isNull():
        return mime

    mime.setImageData(image)

    buffer = QBuffer()
    if buffer.open(QIODevice.OpenModeFlag.WriteOnly) and image.save(buffer, "PNG"):
        mime.setData("image/png", buffer.data())

    return mime


def copy_file_to_clipboard(path: str | Path) -> None:
    """파일을 클립보드에 복사합니다."""

    file_path = Path(path)
    mime = build_file_clipboard_mime_data(file_path)

    if os.name == "nt":
        try:
            _copy_file_to_windows_clipboard(file_path, mime)
            return
        except Exception:
            logger.exception("Windows 네이티브 클립보드 복사 실패, Qt fallback 사용: %s", file_path)

    QApplication.clipboard().setMimeData(mime)


def _copy_file_to_windows_clipboard(path: Path, mime: QMimeData) -> None:
    """Windows 네이티브 클립보드에 파일/이미지 포맷을 함께 기록합니다."""

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    _configure_windows_clipboard_api(user32, kernel32)

    handles_to_free: list[int] = []

    png_bytes = bytes(mime.data("image/png"))
    dib_bytes = _image_to_dib_bytes(mime.imageData()) if mime.hasImage() else b""

    try:
        _open_windows_clipboard(user32)
        user32.EmptyClipboard()

        hdrop = _alloc_global_bytes(kernel32, _build_hdrop_payload(path))
        handles_to_free.append(hdrop)
        _set_clipboard_handle(user32, _CF_HDROP, hdrop)
        handles_to_free.remove(hdrop)

        if dib_bytes:
            h_dib = _alloc_global_bytes(kernel32, dib_bytes)
            handles_to_free.append(h_dib)
            _set_clipboard_handle(user32, _CF_DIB, h_dib)
            handles_to_free.remove(h_dib)

        if png_bytes:
            png_format = user32.RegisterClipboardFormatW("PNG")
            h_png = _alloc_global_bytes(kernel32, png_bytes)
            handles_to_free.append(h_png)
            _set_clipboard_handle(user32, png_format, h_png)
            handles_to_free.remove(h_png)
    finally:
        try:
            user32.CloseClipboard()
        except Exception:
            pass

        for handle in handles_to_free:
            if handle:
                kernel32.GlobalFree(handle)


def _configure_windows_clipboard_api(user32: ctypes.WinDLL, kernel32: ctypes.WinDLL) -> None:
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    user32.RegisterClipboardFormatW.restype = wintypes.UINT

    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.restype = wintypes.HGLOBAL


def _open_windows_clipboard(user32: ctypes.WinDLL, retries: int = 10, delay: float = 0.05) -> None:
    for _ in range(retries):
        if user32.OpenClipboard(None):
            return
        time.sleep(delay)
    raise OSError("클립보드를 열 수 없습니다.")


def _set_clipboard_handle(user32: ctypes.WinDLL, fmt: int, handle: int) -> None:
    if not user32.SetClipboardData(fmt, handle):
        raise OSError(f"SetClipboardData 실패: format={fmt}")


def _alloc_global_bytes(kernel32: ctypes.WinDLL, payload: bytes) -> int:
    handle = kernel32.GlobalAlloc(_GMEM_MOVEABLE, len(payload))
    if not handle:
        raise MemoryError("GlobalAlloc 실패")

    locked = kernel32.GlobalLock(handle)
    if not locked:
        kernel32.GlobalFree(handle)
        raise MemoryError("GlobalLock 실패")

    try:
        ctypes.memmove(locked, payload, len(payload))
    finally:
        kernel32.GlobalUnlock(handle)

    return handle


def _build_hdrop_payload(path: Path) -> bytes:
    file_list = f"{path}\0\0".encode("utf-16le")
    header = struct.pack("IiiII", 20, 0, 0, 0, 1)
    return header + file_list


def _image_to_dib_bytes(image_data: object) -> bytes:
    if isinstance(image_data, QImage):
        image = image_data
    else:
        image = QImage(image_data)

    if image.isNull():
        return b""

    buffer = QBuffer()
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
        return b""
    if not image.save(buffer, "BMP"):
        return b""

    bmp = bytes(buffer.data())
    if len(bmp) <= 14:
        return b""
    return bmp[14:]
