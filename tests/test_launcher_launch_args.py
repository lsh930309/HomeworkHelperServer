from types import SimpleNamespace

from src.core import launcher as launcher_module


def test_launch_target_accepts_args_only_for_direct_targets():
    assert launcher_module.launch_target_accepts_args("C:/Games/ZZZ.exe") is True
    assert launcher_module.launch_target_accepts_args("/Applications/ZZZ.app") is True
    assert launcher_module.launch_target_accepts_args("C:/Games/ZZZ.lnk") is False
    assert launcher_module.launch_target_accepts_args("C:/Games/ZZZ.url") is False
    assert launcher_module.launch_target_accepts_args("steam://run/1234") is False
    assert launcher_module.launch_target_accepts_args("") is False
    assert launcher_module.launch_target_accepts_args(None) is False


def test_launcher_passes_launch_args_as_windows_shell_execute_params(monkeypatch):
    calls = []

    class _FakeShell32:
        def IsUserAnAdmin(self):
            return False

        def ShellExecuteW(self, hwnd, verb, file, params, directory, show):
            calls.append((hwnd, verb, file, params, directory, show))
            return 33

    monkeypatch.setattr(launcher_module.os, "name", "nt")
    monkeypatch.setattr(
        launcher_module.ctypes,
        "windll",
        SimpleNamespace(shell32=_FakeShell32()),
        raising=False,
    )

    assert launcher_module.Launcher(run_as_admin=False).launch_process(
        "C:/Games/ZenlessZoneZero.exe",
        args="  -use-d3d12  ",
    ) is True

    assert calls == [
        (None, "open", "C:/Games/ZenlessZoneZero.exe", "-use-d3d12", None, 1)
    ]


def test_launcher_passes_launch_args_as_posix_popen_list(monkeypatch):
    calls = []

    class _FakePopen:
        def __init__(self, args):
            calls.append(args)

    monkeypatch.setattr(launcher_module.os, "name", "posix")
    monkeypatch.setattr(launcher_module.subprocess, "Popen", _FakePopen)

    assert launcher_module.Launcher().launch_process(
        "/Applications/ZenlessZoneZero.app",
        args='-use-d3d12 --profile "alpha test"',
    ) is True

    assert calls == [["/Applications/ZenlessZoneZero.app", "-use-d3d12", "--profile", "alpha test"]]
