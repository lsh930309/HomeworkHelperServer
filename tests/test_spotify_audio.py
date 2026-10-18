"""Spotify 믹서 실제값 계약: 가짜 프로세스·장치만 사용하고 운영 I/O는 금지한다."""
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from src.core.spotify_audio import SpotifyAudioController, SpotifyAudioSnapshot


class Session:
    def __init__(self, pid=42, level=.37, muted=False):
        self.pid, self.level, self.muted = pid, level, muted
        self.writes = []
        self.fail_read = self.fail_write = self.ignore_write = False

    def get_volume(self):
        if self.fail_read:
            raise OSError("출력 장치 연결 해제")
        return self.level

    def get_mute(self):
        if self.fail_read:
            raise OSError("출력 장치 연결 해제")
        return self.muted

    def set_volume(self, level):
        if self.fail_write:
            raise OSError("오디오 요청 거부")
        self.writes.append(("volume", level))
        if not self.ignore_write:
            self.level = level

    def set_mute(self, muted):
        if self.fail_write:
            raise OSError("오디오 요청 거부")
        self.writes.append(("mute", muted))
        if not self.ignore_write:
            self.muted = muted


class Backend:
    def __init__(self, *sessions):
        self.sessions = list(sessions)
        self.valid = {42, 99}
        self.enumerations = 0
        self.verifications = []
        self.error = False

    def enumerate_sessions(self):
        self.enumerations += 1
        if self.error:
            raise OSError("Windows Audio 접근 실패")
        return tuple(self.sessions)

    def verify_identity(self, process):
        self.verifications.append(process)
        return process.pid in self.valid


@pytest.fixture
def process():
    return SimpleNamespace(pid=42, create_time=123.0, path=r"C:\Spotify\Spotify.exe")


def controller(backend, *processes):
    return SpotifyAudioController(backend=backend, process_reader=lambda: processes)


def test_observing_existing_37_percent_and_external_changes_never_writes(process):
    session = Session()
    audio = controller(Backend(session), process)
    assert audio.snapshot() == SpotifyAudioSnapshot(volume=37, muted=False, available=True)
    session.level = .58
    session.muted = True
    assert audio.snapshot() == SpotifyAudioSnapshot(volume=58, muted=True, available=True)
    assert session.writes == []


def test_snapshot_is_immutable_and_no_runtime_copy_overwrites_windows(process):
    session = Session()
    audio = controller(Backend(session), process)
    observation = audio.snapshot()
    with pytest.raises(FrozenInstanceError):
        observation.volume = 100
    session.level = .22
    assert observation.volume == 37
    assert audio.snapshot().volume == 22 and not session.writes


def test_new_output_device_and_new_session_are_discovered_without_auto_apply(process):
    old = Session(level=.37)
    backend = Backend(old)
    audio = controller(backend, process)
    audio.snapshot()
    replacement = Session(level=.16, muted=True)
    backend.sessions[:] = [replacement]
    assert audio.snapshot() == SpotifyAudioSnapshot(16, True, True)
    extra = Session(level=.71, muted=False)
    backend.sessions.append(extra)
    assert audio.snapshot() == SpotifyAudioSnapshot(71, False, True)
    assert old.writes == replacement.writes == extra.writes == []
    assert backend.enumerations == 3


def test_all_verified_spotify_processes_and_outputs_receive_explicit_change(process):
    second = SimpleNamespace(pid=99, create_time=124.0, path=process.path)
    first, other_output, other_pid, unrelated = Session(), Session(), Session(99), Session(777)
    backend = Backend(first, other_output, other_pid, unrelated)
    audio = controller(backend, process, second)
    assert audio.set_volume(61)
    assert audio.set_mute(True)
    assert audio.snapshot() == SpotifyAudioSnapshot(61, True, True)
    assert all(session.writes == [("volume", .61), ("mute", True)]
               for session in (first, other_output, other_pid))
    assert unrelated.writes == []


def test_process_reader_is_refreshed_on_every_operation(process):
    sessions = Backend(Session())
    observed = [process]
    audio = SpotifyAudioController(sessions, process_reader=lambda: tuple(observed))
    assert audio.snapshot().available
    observed.clear()
    assert audio.snapshot() == SpotifyAudioSnapshot()
    assert not audio.set_volume(100) and not audio.set_mute(True)
    assert sessions.sessions[0].writes == []


def test_other_user_session_and_unrelated_process_are_never_modified(process):
    foreign, unrelated = Session(), Session(777)
    backend = Backend(foreign, unrelated)
    backend.valid.clear()
    audio = controller(backend, process)
    assert audio.snapshot() == SpotifyAudioSnapshot()
    assert not audio.set_volume(80) and not audio.set_mute(True)
    assert foreign.writes == unrelated.writes == []


def test_identity_is_checked_before_each_write_when_pid_changes_mid_request(process):
    first, second = Session(), Session()
    backend = Backend(first, second)
    def verify(target):
        assert target is process
        # 첫 세션은 유효하지만 다음 세션에 접근할 때는 PID가 재사용되었다.
        return not first.writes
    backend.verify_identity = verify
    audio = controller(backend, process)
    assert not audio.set_volume(48)
    assert first.writes == [("volume", .48)] and second.writes == []


@pytest.mark.parametrize("action,value", [("set_volume", 62), ("set_mute", True)])
def test_partial_failure_returns_false_and_remaining_sessions_still_apply(process, action, value):
    failed, healthy = Session(), Session()
    failed.fail_write = True
    audio = controller(Backend(failed, healthy), process)
    assert getattr(audio, action)(value) is False
    expected = [("volume", .62)] if action == "set_volume" else [("mute", True)]
    assert healthy.writes == expected


@pytest.mark.parametrize("action,value", [("set_volume", 62), ("set_mute", True)])
def test_ignored_write_is_not_reported_as_applied(process, action, value):
    session = Session()
    session.ignore_write = True
    audio = controller(Backend(session), process)
    assert getattr(audio, action)(value) is False
    assert audio.snapshot() == SpotifyAudioSnapshot(37, False, True)


def test_partial_read_failure_is_unavailable_instead_of_resetting_to_100(process):
    failed, healthy = Session(), Session(level=.91)
    failed.fail_read = True
    audio = controller(Backend(failed, healthy), process)
    assert audio.snapshot() == SpotifyAudioSnapshot()
    assert failed.writes == healthy.writes == []


@pytest.mark.parametrize("level", [float("nan"), float("inf"), -.1, 1.1])
def test_invalid_native_value_is_unknown_not_a_default_volume(process, level):
    audio = controller(Backend(Session(level=level)), process)
    assert audio.snapshot() == SpotifyAudioSnapshot()


def test_audio_service_failure_and_missing_process_are_unavailable(process):
    backend = Backend(Session())
    backend.error = True
    audio = controller(backend, process)
    assert audio.snapshot() == SpotifyAudioSnapshot()
    assert not audio.set_volume(70) and not audio.set_mute(False)
    assert not backend.sessions[0].writes
    assert controller(Backend(), process).snapshot() == SpotifyAudioSnapshot()


def test_process_reader_failure_does_not_write_or_claim_100_percent():
    backend = Backend(Session())
    def failed():
        raise OSError("사용자 세션 조회 실패")
    audio = SpotifyAudioController(backend, process_reader=failed)
    assert audio.snapshot() == SpotifyAudioSnapshot()
    assert not audio.set_volume(70) and not audio.set_mute(False)
    assert not backend.sessions[0].writes and backend.enumerations == 0


@pytest.mark.parametrize("value", [-1, 101, True, False, 37.5, "37", None])
def test_invalid_volume_request_does_not_enumerate_or_write(process, value):
    backend = Backend(Session())
    audio = controller(backend, process)
    assert not audio.set_volume(value)
    assert backend.enumerations == 0 and backend.sessions[0].writes == []


@pytest.mark.parametrize("value", [0, 1, "true", None])
def test_invalid_mute_request_does_not_enumerate_or_write(process, value):
    backend = Backend(Session())
    audio = controller(backend, process)
    assert not audio.set_mute(value)
    assert backend.enumerations == 0 and backend.sessions[0].writes == []


def test_volume_zero_and_mute_are_independent_explicit_controls(process):
    session = Session()
    audio = controller(Backend(session), process)
    assert audio.set_volume(0)
    assert audio.snapshot() == SpotifyAudioSnapshot(0, False, True)
    assert audio.set_mute(True) and audio.set_volume(37)
    assert audio.snapshot() == SpotifyAudioSnapshot(37, True, True)
    assert audio.set_mute(False)
    assert audio.snapshot() == SpotifyAudioSnapshot(37, False, True)
