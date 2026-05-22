from pathlib import Path

from src.utils.app_paths import (
    DEFAULT_SERVER_MUTEX_NAME,
    get_app_data_dir,
    get_server_mutex_name,
    get_testbench_session_id,
    is_testbench_mode,
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
