"""Spotify 준비는 가짜 프로세스·Shell만 사용하며 운영 앱을 실행하지 않는다."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from src.core import spotify_app


class Gone(Exception):
    pass


class Denied(Exception):
    pass


class Process:
    def __init__(self, pid=41, *, path=None, name="Spotify.exe", owner=True,
                 times=(123.0, 123.0), failure=None):
        self.pid = pid
        self.info = {"name": name}
        self.path = path or r"C:\Program Files\WindowsApps\SpotifyAB.SpotifyMusic_1.2.99.1_x64__zpdnekdrzrea0\Spotify.exe"
        self.owner = owner
        self.times = iter(times)
        self.failure = failure
        self.reads = []

    def _read(self, name):
        self.reads.append(name)
        if self.failure and self.failure[0] == name:
            raise self.failure[1]("controlled native process failure")

    def create_time(self):
        self._read("create_time")
        return next(self.times)

    def exe(self):
        self._read("exe")
        return self.path


@pytest.fixture
def native(monkeypatch):
    processes, calls = [], []

    def process_iter(attributes):
        calls.append(("enumerate", attributes))
        return tuple(processes)

    def belongs(process):
        process._read("owner")
        return process.owner

    def launch(uri, **kwargs):
        calls.append(("launch", uri, kwargs))

    monkeypatch.setitem(sys.modules, "psutil", SimpleNamespace(
        process_iter=process_iter, NoSuchProcess=Gone, AccessDenied=Denied))
    monkeypatch.setitem(sys.modules, "src.core.process_monitor", SimpleNamespace(
        _belongs_to_current_user_session=belongs))
    monkeypatch.setattr(spotify_app, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(spotify_app, "os", SimpleNamespace(
        environ={"APPDATA": r"C:\Users\owner\AppData\Roaming",
                 "LOCALAPPDATA": r"C:\Users\owner\AppData\Local",
                 "ProgramFiles": r"C:\Program Files",
                 "ProgramFiles(x86)": r"C:\Program Files (x86)"},
        startfile=launch))
    return processes, calls


@pytest.mark.parametrize("path", [
    r"C:\Users\owner\AppData\Roaming\Spotify\Spotify.exe",
    r"C:\Users\owner\AppData\Local\Spotify\Spotify.exe",
    r"C:\Program Files\Spotify\Spotify.exe",
    r"C:\Program Files (x86)\Spotify\Spotify.exe",
    r"C:\Program Files\WindowsApps\SpotifyAB.SpotifyMusic_1.2.99.1_x64__zpdnekdrzrea0\Spotify.exe",
    r"c:\program files\windowsapps\SPOTIFYAB.SPOTIFYMUSIC_1.3.0.0_ARM64__ZPDNEKDRZREA0\SPOTIFY.EXE",
])
def test_recognized_desktop_and_updated_store_paths_are_observed(native, path):
    processes, calls = native
    processes.append(Process(path=path))
    assert spotify_app.spotify_processes() == (spotify_app.SpotifyProcess(41, 123.0, path),)
    assert calls == [("enumerate", ["name"])]


@pytest.mark.parametrize("path", [
    r"C:\Downloads\Spotify.exe",
    r"C:\Users\someone_else\AppData\Local\Spotify\Spotify.exe",
    r"C:\Program Files\WindowsApps\Other.SpotifyMusic_1.2_x64__zpdnekdrzrea0\Spotify.exe",
    r"C:\Program Files\WindowsApps\SpotifyAB.SpotifyMusic_1.2_x64__otherpublisher\Spotify.exe",
    r"C:\Program Files\WindowsApps\SpotifyAB.SpotifyMusic_1.2_x64__zpdnekdrzrea0\child\Spotify.exe",
    r"C:\Program Files\WindowsAppsCopy\SpotifyAB.SpotifyMusic_1.2_x64__zpdnekdrzrea0\Spotify.exe",
    r"C:\Program Files\Spotify\SpotifyLauncher.exe",
])
def test_matching_filename_does_not_make_unregistered_path_spotify(native, path):
    processes, calls = native
    processes.append(Process(path=path))
    assert spotify_app.spotify_processes() == ()
    assert all(call[0] != "launch" for call in calls)


def test_missing_environment_never_recognizes_relative_spotify_path(native):
    spotify_app.os.environ.clear()
    assert not spotify_app._spotify_executable(r"Spotify\Spotify.exe")
    assert not spotify_app._spotify_executable(r"WindowsApps\SpotifyAB.SpotifyMusic_1_x64__zpdnekdrzrea0\Spotify.exe")


@pytest.mark.parametrize("folder", ["Roaming", "Local"])
def test_explicit_profile_inputs_recognize_desktop_without_changing_isolated_environment(native, folder):
    processes, calls = native
    processes.append(Process(path=rf"C:\Users\actual\AppData\{folder}\Spotify\Spotify.exe"))
    spotify_app.os.environ["APPDATA"] = "isolated-roaming"
    spotify_app.os.environ["LOCALAPPDATA"] = "isolated-local"
    before = dict(spotify_app.os.environ)
    assert [process.pid for process in spotify_app.spotify_processes(
        appdata=r"C:\Users\actual\AppData\Roaming", local_appdata=r"C:\Users\actual\AppData\Local")] == [41]
    assert spotify_app.os.environ == before
    assert calls == [("enumerate", ["name"])]


def test_other_user_or_session_and_launcher_are_excluded_before_path_read(native):
    processes, _ = native
    wrong_user = Process(42, owner=False)
    wrong_session = Process(43, owner=False)
    launcher = Process(44, name="SpotifyLauncher.exe")
    processes.extend([wrong_user, wrong_session, launcher, Process(45)])
    assert [item.pid for item in spotify_app.spotify_processes()] == [45]
    assert wrong_user.reads == wrong_session.reads == ["owner"]
    assert launcher.reads == []


def test_reused_pid_never_counts_as_running_spotify(native):
    processes, _ = native
    processes.append(Process(times=(123.0, 999.0)))
    assert spotify_app.spotify_processes() == ()


@pytest.mark.parametrize("still_running", [False, True])
def test_native_session_error_only_becomes_absent_after_confirmed_process_exit(native, still_running):
    processes, _ = native
    ending = Process(failure=("owner", OSError))
    ending.is_running = lambda: still_running
    processes.extend((ending, Process(99)))
    if still_running:
        with pytest.raises(OSError, match="controlled native process failure"):
            spotify_app.spotify_processes()
    else:
        assert [process.pid for process in spotify_app.spotify_processes()] == [99]


@pytest.mark.parametrize("error", [Gone, Denied])
@pytest.mark.parametrize("stage", ["owner", "create_time", "exe"])
def test_process_disappearance_is_absent_but_denial_is_unknown(native, error, stage):
    processes, calls = native
    processes.extend([Process(failure=(stage, error)), Process(99)])
    if error is Gone:
        assert [item.pid for item in spotify_app.spotify_processes()] == [99]
    else:
        with pytest.raises(OSError, match="권한") as raised:
            spotify_app.spotify_processes()
        assert isinstance(raised.value.__cause__, Denied)
    assert all(call[0] != "launch" for call in calls)


@pytest.mark.parametrize("operation", [spotify_app.spotify_processes, spotify_app.launch_spotify])
def test_non_windows_fails_without_enumeration_or_shell_request(native, operation):
    _, calls = native
    spotify_app.sys.platform = "darwin"
    with pytest.raises(OSError, match="Windows"):
        operation()
    assert calls == []


@pytest.mark.parametrize("dj,uri", [(False, "spotify:"), (True, "spotify:playlist:37i9dQZF1EYkqdzj48dyYq")])
def test_only_fixed_uri_is_requested_once_without_activation(native, dj, uri):
    _, calls = native
    assert spotify_app.launch_spotify(dj=dj) is True
    assert calls == [("launch", uri, {"show_cmd": 7})]


def test_launch_failure_propagates_without_retry_or_alternate_path(native):
    _, calls = native

    def failed(uri, **kwargs):
        calls.append((uri, kwargs))
        raise OSError("Spotify URI handler unavailable")

    spotify_app.os.startfile = failed
    with pytest.raises(OSError, match="handler unavailable"):
        spotify_app.launch_spotify(dj=True)
    assert calls == [(spotify_app.SPOTIFY_DJ_URI, {"show_cmd": 7})]
    with pytest.raises(TypeError):
        spotify_app.launch_spotify(path=r"C:\Downloads\Spotify.exe")
    assert len(calls) == 1


def test_module_import_does_not_observe_or_launch(monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, "psutil", SimpleNamespace(
        process_iter=lambda *_args: calls.append("enumerate")))
    import os
    monkeypatch.setattr(os, "startfile", lambda *_args, **_kwargs: calls.append("launch"), raising=False)
    name = "isolated_spotify_app_import"
    spec = importlib.util.spec_from_file_location(name, Path(spotify_app.__file__))
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    assert calls == []


@pytest.fixture
def window_native(native, monkeypatch):
    import ctypes
    from src.utils import audio_control

    windows, calls = [], []
    control = SimpleNamespace(identity=True, accepted=True, failure=None)
    def lookup(hwnd):
        return next(window for window in windows if window["hwnd"] == hwnd)
    def enumerate_windows(callback, context):
        calls.append(("enumerate_windows",))
        for window in windows:
            callback(window["hwnd"], context)
    def owner(hwnd, mode):
        assert mode == 4
        return lookup(hwnd).get("owner", 0)
    def process_id(hwnd):
        window = lookup(hwnd)
        pid = window.get("pid", 41)
        if isinstance(pid, list):
            pid = pid.pop(0)
        calls.append(("window_pid", hwnd, pid))
        return 9, pid
    def verify(process):
        calls.append(("identity", process))
        return control.identity
    def iconic(hwnd):
        calls.append(("iconic", hwnd))
        return lookup(hwnd).get("iconic", False)
    def show(hwnd, mode):
        calls.append(("show", hwnd, mode))
        if control.failure:
            raise control.failure
        return control.accepted
    monkeypatch.setitem(sys.modules, "win32gui", SimpleNamespace(
        EnumWindows=enumerate_windows, GetWindow=owner, IsIconic=iconic,
        IsWindowVisible=lambda hwnd: lookup(hwnd).get("visible", True)))
    monkeypatch.setitem(sys.modules, "win32process", SimpleNamespace(
        GetWindowThreadProcessId=process_id))
    monkeypatch.setattr(audio_control, "verify_identity", verify)
    monkeypatch.setattr(ctypes, "WinDLL", lambda *_args, **_kwargs: SimpleNamespace(
        ShowWindowAsync=show), raising=False)
    return native[0], windows, calls, control


def test_cold_minimization_only_requests_first_new_spotify_window(window_native):
    processes, windows, calls, _ = window_native
    processes.extend([Process(41), Process(42)])
    windows.extend([{"hwnd": 10, "pid": 99}, {"hwnd": 11, "pid": 41},
                    {"hwnd": 12, "pid": 42}])
    assert spotify_app.minimize_spotify_window(123.0, is_current=lambda: True)
    assert [call for call in calls if call[0] == "show"] == [("show", 11, 7)]
    verified = [call[1] for call in calls if call[0] == "identity"]
    assert verified == [spotify_app.SpotifyProcess(41, 123.0, processes[0].path)]
    assert [call for call in calls if call[:2] == ("window_pid", 11)] == [
        ("window_pid", 11, 41), ("window_pid", 11, 41)]


@pytest.mark.parametrize("window", [
    {"hwnd": 10, "visible": False}, {"hwnd": 10, "owner": 99},
    {"hwnd": 10, "pid": 99},
])
def test_hidden_owned_or_other_process_window_is_not_a_candidate(window_native, window):
    processes, windows, calls, _ = window_native
    processes.append(Process())
    windows.append(window)
    assert not spotify_app.minimize_spotify_window(123.0, is_current=lambda: True)
    assert not any(call[0] in {"show", "identity"} for call in calls)


@pytest.mark.parametrize("process", [
    Process(times=(122.9, 122.9)), Process(owner=False),
    Process(path=r"C:\Downloads\Spotify.exe"), Process(times=(123.0, 999.0)),
])
def test_old_foreign_or_unverified_process_never_causes_window_access(window_native, process):
    processes, windows, calls, _ = window_native
    processes.append(process)
    windows.append({"hwnd": 10})
    assert not spotify_app.minimize_spotify_window(123.0, is_current=lambda: True)
    assert calls == []


def test_minimization_does_not_touch_processes_when_request_already_cancelled(window_native):
    processes, windows, calls, _ = window_native
    processes.append(Process())
    windows.append({"hwnd": 10})
    assert not spotify_app.minimize_spotify_window(123.0, is_current=lambda: False)
    assert calls == [] and processes[0].reads == []


def test_cancelled_just_before_window_request_is_never_sent(window_native):
    processes, windows, calls, _ = window_native
    processes.append(Process())
    windows.append({"hwnd": 10})
    assert not spotify_app.minimize_spotify_window(
        123.0, is_current=lambda: not any(call[0] == "iconic" for call in calls))
    assert not any(call[0] == "show" for call in calls)


def test_reused_pid_or_changed_window_owner_does_not_receive_stale_request(window_native):
    processes, windows, calls, control = window_native
    processes.append(Process())
    windows.append({"hwnd": 10})
    control.identity = False
    assert not spotify_app.minimize_spotify_window(123.0, is_current=lambda: True)
    assert not any(call[0] == "show" for call in calls)


def test_window_process_is_rechecked_immediately_before_minimization(window_native):
    processes, windows, calls, _ = window_native
    processes.append(Process())
    windows.append({"hwnd": 10, "pid": [41, 99]})
    assert not spotify_app.minimize_spotify_window(123.0, is_current=lambda: True)
    assert not any(call[0] in {"show", "iconic"} for call in calls)


@pytest.mark.parametrize("changed", [{"visible": False}, {"owner": 99}])
def test_window_closed_to_tray_or_replaced_by_owned_window_is_not_reopened(window_native, monkeypatch, changed):
    from src.utils import audio_control
    processes, windows, calls, _ = window_native
    processes.append(Process())
    windows.append({"hwnd": 10})
    verify = audio_control.verify_identity
    def changed_window(process):
        matched = verify(process)
        windows[0].update(changed)
        return matched
    monkeypatch.setattr(audio_control, "verify_identity", changed_window)
    assert not spotify_app.minimize_spotify_window(123.0, is_current=lambda: True)
    assert not any(call[0] in {"show", "iconic"} for call in calls)


def test_already_minimized_window_completes_without_another_request(window_native):
    processes, windows, calls, _ = window_native
    processes.append(Process())
    windows.append({"hwnd": 10, "iconic": True})
    assert spotify_app.minimize_spotify_window(123.0, is_current=lambda: True)
    assert not any(call[0] == "show" for call in calls)
    assert any(call[0] == "identity" for call in calls)


@pytest.mark.parametrize("failure", [None, OSError("native window failure")])
def test_native_minimization_failure_propagates_without_second_window_or_fallback(window_native, failure):
    processes, windows, calls, control = window_native
    processes.append(Process())
    windows.extend([{"hwnd": 10}, {"hwnd": 11}])
    control.accepted, control.failure = False, failure
    with pytest.raises(OSError, match="native window failure|최소화"):
        spotify_app.minimize_spotify_window(123.0, is_current=lambda: True)
    assert [call for call in calls if call[0] == "show"] == [("show", 10, 7)]


def test_window_minimization_rejects_non_windows_before_native_access(window_native):
    processes, windows, calls, _ = window_native
    spotify_app.sys.platform = "darwin"
    with pytest.raises(OSError, match="Windows"):
        spotify_app.minimize_spotify_window(123.0, is_current=lambda: True)
    assert calls == []
