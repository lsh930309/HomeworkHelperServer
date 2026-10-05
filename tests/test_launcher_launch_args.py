from types import SimpleNamespace

from src.core import launcher as launcher_module


def test_launch_target_accepts_args_only_for_direct_targets():
    assert launcher_module.launch_target_accepts_args("C:/Games/ZZZ.exe") is True
    assert launcher_module.launch_target_accepts_args("/Applications/ZZZ.app") is True
    assert launcher_module.launch_target_accepts_args("C:/Games/ZZZ.lnk") is False
    assert launcher_module.launch_target_accepts_args("C:/Games/ZZZ.url") is False
    assert launcher_module.launch_target_accepts_args("steam://run/1234") is False
    assert launcher_module.launch_target_accepts_args("microsoft-edge:") is False
    assert launcher_module.launch_target_accepts_args("shell:AppsFolder\\Game") is False
    assert launcher_module.launch_target_accepts_args("mailto:user@example.test") is False
    assert launcher_module.launch_target_accepts_args("") is False
    assert launcher_module.launch_target_accepts_args(None) is False


def test_normal_windows_launch_separates_executable_and_arguments_without_uac(monkeypatch):
    calls = []
    monkeypatch.setattr(launcher_module.os, "name", "nt")
    monkeypatch.setattr(launcher_module.subprocess, "Popen", lambda command, *, executable: calls.append((command, executable)))
    assert launcher_module.Launcher(run_as_admin=False).launch_process("C:/Games/Zenless Zone Zero.exe", args="  -use-d3d12  ")
    assert calls == [('"C:/Games/Zenless Zone Zero.exe" -use-d3d12', "C:/Games/Zenless Zone Zero.exe")]


def test_normal_windows_admin_manifest_fails_without_elevation_fallback(monkeypatch):
    monkeypatch.setattr(launcher_module.os, "name", "nt")
    def require_elevation(*_args, **_kwargs):
        error = OSError("elevation required")
        error.winerror = 740
        raise error
    monkeypatch.setattr(launcher_module.subprocess, "Popen", require_elevation)
    launcher = launcher_module.Launcher(run_as_admin=False)
    assert launcher.launch_process("C:/Games/game.exe") is False
    assert "관리자 권한이 필요" in launcher.last_error


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


def test_launcher_preserves_posix_command_string_without_extra_args(monkeypatch):
    calls = []

    class _FakePopen:
        def __init__(self, args):
            calls.append(args)

    monkeypatch.setattr(launcher_module.os, "name", "posix")
    monkeypatch.setattr(launcher_module.subprocess, "Popen", _FakePopen)

    assert launcher_module.Launcher().launch_process("python -m homework_helper") is True

    assert calls == [["python", "-m", "homework_helper"]]


def test_launcher_keeps_existing_posix_target_path_with_spaces_when_args_are_added(monkeypatch, tmp_path):
    calls = []
    app_path = tmp_path / "Zenless Zone Zero.app"
    app_path.mkdir()

    class _FakePopen:
        def __init__(self, args):
            calls.append(args)

    monkeypatch.setattr(launcher_module.os, "name", "posix")
    monkeypatch.setattr(launcher_module.subprocess, "Popen", _FakePopen)

    assert launcher_module.Launcher().launch_process(str(app_path), args="-use-d3d12") is True

    assert calls == [[str(app_path), "-use-d3d12"]]


def test_saved_launch_selection_is_shared_for_gui_api_and_broker():
    from src.core.launch_target import launcher_candidates, resolve_launch_target, resolve_launch_args
    process = SimpleNamespace(
        monitoring_path="C:/Games/game.exe", launch_path="C:/Games/game.url",
        preferred_launch_type="direct", launch_args_enabled=True, launch_args="  --profile alpha  ",
    )
    direct, mode = resolve_launch_target(process)
    assert (direct, mode, resolve_launch_args(process, mode, direct)) == ("C:/Games/game.exe", "direct", "--profile alpha")
    shortcut, mode = resolve_launch_target(process, "shortcut")
    assert (shortcut, mode, resolve_launch_args(process, mode, shortcut)) == ("C:/Games/game.url", "shortcut", None)
    candidates = launcher_candidates(process, ["launcher.exe"])
    launcher, mode = resolve_launch_target(process, "launcher", launcher_patterns=["launcher.exe"], existing_paths=candidates)
    assert launcher == r"C:/Games\launcher.exe"
    assert resolve_launch_args(process, mode, launcher) is None
    assert process.preferred_launch_type == "direct"


def test_privileged_managed_launch_sends_registered_identity_only(monkeypatch):
    monkeypatch.setattr(launcher_module.os, "name", "nt")
    calls = []
    client = SimpleNamespace(launch_managed=lambda process_id, *, mode: calls.append((process_id, mode)) or {"accepted": True})
    launcher = launcher_module.Launcher(run_as_admin=True, privilege_client=client)
    assert launcher.launch_process("C:/Games/game.exe", args="--private-value", managed_process_id="game-id", launch_mode="direct")
    assert calls == [("game-id", "direct")]


def test_privileged_service_failure_never_falls_back_to_shell_or_uac(monkeypatch):
    from src.host_service.client import PrivilegeServiceUnavailable
    monkeypatch.setattr(launcher_module.os, "name", "nt")
    def unavailable(*_args, **_kwargs):
        raise PrivilegeServiceUnavailable("service unavailable")
    launcher = launcher_module.Launcher(run_as_admin=True, privilege_client=SimpleNamespace(launch_managed=unavailable))
    assert launcher.launch_process("C:/Games/game.exe", managed_process_id="game-id", launch_mode="direct") is False
    assert launcher.last_error == "service unavailable"
    assert launcher.launch_process("C:/Games/game.exe") is False
    assert "등록된" in launcher.last_error


def test_running_normal_launcher_is_not_restarted_without_user_decision(monkeypatch):
    monkeypatch.setattr(launcher_module.os, "name", "nt")
    calls = []
    process = SimpleNamespace(name=lambda: "Steam.exe", terminate=lambda: calls.append("terminate"))
    launcher = launcher_module.Launcher(run_as_admin=True, privilege_client=SimpleNamespace(launch_managed=lambda *_args, **_kwargs: calls.append("service")))
    monkeypatch.setattr(launcher, "_find_launcher_process", lambda prefix: (process, False))
    assert launcher.launch_process("steam://run/1234", managed_process_id="game-id") is False
    assert calls == []


def test_unsafe_launcher_is_not_restarted_even_after_confirmation_is_registered(monkeypatch):
    monkeypatch.setattr(launcher_module.os, "name", "nt")
    calls = []
    process = SimpleNamespace(name=lambda: "Steam.exe", terminate=lambda: calls.append("terminate"))
    launcher = launcher_module.Launcher(run_as_admin=True, privilege_client=SimpleNamespace(launch_managed=lambda *_args, **_kwargs: calls.append("service")))
    launcher.launcher_restart_callback = lambda _name: calls.append("confirm") or True
    monkeypatch.setattr(launcher, "_find_launcher_process", lambda prefix: (process, False))
    monkeypatch.setattr(launcher_module, "should_restart_launcher", lambda _process: False)
    assert launcher.launch_process("steam://run/1234", managed_process_id="game-id") is False
    assert calls == []


def test_headless_policy_preserves_game_protocol_and_web_shortcut_privileges(monkeypatch, tmp_path):
    from src.core import launch_policy
    game = tmp_path / 'game.url'
    web = tmp_path / 'web.url'
    game.write_text('[InternetShortcut]\nURL=steam://run/1234\n', encoding='utf-8')
    web.write_text('[InternetShortcut]\nURL=https://example.test/game?value=100%25\n', encoding='utf-8')
    monkeypatch.setattr(launch_policy.os, 'name', 'nt')
    assert launch_policy.launch_admin_required(str(game)) is True
    assert launch_policy.launch_admin_required(str(web)) is False
    assert launch_policy.read_url_target(str(web)) == 'https://example.test/game?value=100%25'
