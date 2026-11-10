from pathlib import Path
from types import SimpleNamespace

import pytest

from src.utils.app_paths import (
    CapturePathError,
    DEFAULT_SERVER_MUTEX_NAME,
    get_app_data_dir,
    get_server_mutex_name,
    get_testbench_session_id,
    is_testbench_mode,
    validate_capture_output_path,
)


def test_testbench_appdata_override_is_final_app_root(monkeypatch, tmp_path):
    isolated = tmp_path / "HHHostTestbench" / "case-1" / "appdata"
    monkeypatch.setenv("HH_TEST_APPDATA_DIR", str(isolated))

    resolved = Path(get_app_data_dir())

    assert resolved == isolated
    assert resolved.exists()
    assert is_testbench_mode() is True


def test_testbench_session_derives_safe_mutex_when_explicit_mutex_missing(monkeypatch):
    monkeypatch.delenv("HH_SERVER_MUTEX_NAME", raising=False)
    monkeypatch.setenv("HH_TESTBENCH_SESSION_ID", "case 1/with spaces")

    assert get_testbench_session_id() == "case_1_with_spaces"
    assert get_server_mutex_name() == f"{DEFAULT_SERVER_MUTEX_NAME}_case_1_with_spaces"


def test_explicit_mutex_override_wins(monkeypatch):
    monkeypatch.setenv("HH_TESTBENCH_SESSION_ID", "case-1")
    monkeypatch.setenv("HH_SERVER_MUTEX_NAME", r"Local\CustomMutex")

    assert get_server_mutex_name() == r"Local\CustomMutex"


def test_capture_directory_rejects_app_data_root_descendants_and_links(monkeypatch, tmp_path):
    data = tmp_path / "HomeworkHelper"
    data.mkdir()
    sibling = tmp_path / "HomeworkHelper-Captures"
    link = tmp_path / "capture-link"
    monkeypatch.setenv("HH_TEST_APPDATA_DIR", str(data))
    try:
        link.symlink_to(data, target_is_directory=True)
    except OSError as error:
        if getattr(error, "winerror", None) != 1314:
            raise
        pytest.skip("Windows directory symlinks require Developer Mode or appropriate permission")

    for location in (data, data / "new", sibling / ".." / data.name / "new", link / "new"):
        with pytest.raises(CapturePathError, match="호스트 앱 데이터 폴더"):
            validate_capture_output_path(location)
    assert validate_capture_output_path(sibling / "new") == sibling.resolve() / "new"
    assert not sibling.exists() and not (data / "new").exists()


@pytest.mark.parametrize("windowed", [False, True])
def test_screenshot_refuses_app_data_before_opening_native_capture(windowed, monkeypatch, tmp_path):
    from src.screenshot import capture

    protected = tmp_path / "state" / "protected-captures"
    valid = tmp_path / "external-captures"
    monkeypatch.setenv("HH_TEST_APPDATA_DIR", str(protected.parent))
    events = []

    def save(path, *_geometry):
        events.append(path)
        path.write_bytes(b"fake screenshot")
        return str(path)

    monkeypatch.setattr(capture, "_try_mss", save)
    monkeypatch.setattr(capture, "_try_mss_region", save)
    monkeypatch.setattr(capture, "_get_client_region", lambda _hwnd: (0, 0, 1, 1))
    monkeypatch.setattr(capture.ctypes, "windll", SimpleNamespace(user32=SimpleNamespace(
        ShowCursor=lambda visible: events.append(visible))), raising=False)

    def screenshot(path):
        return (capture.take_screenshot_window(123, str(path)) if windowed
                else capture.take_screenshot(str(path)))

    with pytest.raises(CapturePathError, match="호스트 앱 데이터 폴더"):
        screenshot(protected)
    assert events == [] and not protected.exists()
    result = Path(screenshot(valid))
    assert result.parent == valid.resolve() and result.read_bytes() == b"fake screenshot"
