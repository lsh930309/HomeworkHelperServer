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
