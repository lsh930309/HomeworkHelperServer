from src.utils import windows


def test_windows_startup_helpers_are_safe_noops_off_windows(monkeypatch):
    monkeypatch.setattr(windows.os, "name", "posix", raising=False)

    assert windows.is_windows() is False
    assert windows.get_startup_registry_status() is False
    assert windows.get_startup_shortcut_status() is False
    assert windows.set_startup_registry(True) is False
    assert windows.set_startup_shortcut(True) is False

