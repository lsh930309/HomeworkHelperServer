from pathlib import Path

from PyQt6.QtGui import QImage, QColor

from src.utils.clipboard import build_file_clipboard_mime_data, _build_hdrop_payload


def _make_image(path: Path) -> None:
    image = QImage(4, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("#ff3366"))
    assert image.save(str(path), "PNG")


def test_build_file_clipboard_mime_data_keeps_file_url(tmp_path: Path) -> None:
    image_path = tmp_path / "capture.png"
    _make_image(image_path)

    mime = build_file_clipboard_mime_data(image_path)

    urls = mime.urls()
    assert len(urls) == 1
    assert Path(urls[0].toLocalFile()) == image_path


def test_build_file_clipboard_mime_data_adds_image_payload_for_images(tmp_path: Path) -> None:
    image_path = tmp_path / "capture.png"
    _make_image(image_path)

    mime = build_file_clipboard_mime_data(image_path)

    assert mime.hasImage()
    assert bytes(mime.data("image/png")).startswith(b"\x89PNG\r\n\x1a\n")


def test_build_file_clipboard_mime_data_skips_image_payload_for_non_images(tmp_path: Path) -> None:
    file_path = tmp_path / "note.txt"
    file_path.write_text("hello", encoding="utf-8")

    mime = build_file_clipboard_mime_data(file_path)

    assert not mime.hasImage()
    assert bytes(mime.data("image/png")) == b""


def test_build_hdrop_payload_uses_double_null_terminated_utf16_path(tmp_path: Path) -> None:
    file_path = tmp_path / "캡처.png"
    payload = _build_hdrop_payload(file_path)

    assert payload[:4] == (20).to_bytes(4, "little")
    assert payload[20:].endswith("\0\0".encode("utf-16le"))
    assert str(file_path).encode("utf-16le") in payload[20:]
