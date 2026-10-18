"""게임 소리 정책을 fake 세션으로 검증한다. 운영 오디오/프로세스/DB 접근 없음."""
from dataclasses import replace
from types import SimpleNamespace
import sys

import pytest

from src.core.game_audio import GameAudioCoordinator, GameAudioTarget
from src.utils import audio_control


class Session:
    def __init__(self, pid=42, instance="one", endpoint="speakers", level=0.8, muted=False):
        self.pid = pid
        self.key = endpoint, instance
        self.level = level
        self.muted = muted
        self.writes = []
        self.fail_read = False
        self.fail_write = False
        self.ignore_mute = False

    def get_volume(self):
        if self.fail_read:
            raise OSError("device removed")
        return self.level

    def get_mute(self):
        if self.fail_read:
            raise OSError("device removed")
        return self.muted

    def set_volume(self, level):
        if self.fail_write:
            raise OSError("write failed")
        self.writes.append(("volume", level))
        self.level = level

    def set_mute(self, muted):
        if self.fail_write:
            raise OSError("write failed")
        self.writes.append(("mute", muted))
        if not self.ignore_mute:
            self.muted = muted


class Backend:
    def __init__(self, *sessions):
        self.sessions = list(sessions)
        self.valid = True
        self.error = None
        self.enumerations = 0

    def verify_identity(self, target):
        return self.valid

    def enumerate_sessions(self):
        self.enumerations += 1
        if self.error:
            raise self.error
        return tuple(self.sessions)


@pytest.fixture
def target():
    return GameAudioTarget("game", 42, 123.0, "/game.exe", False, None)


def test_background_policy_switches_games_without_changing_user_preferences(target):
    first, second = Session(), Session(pid=99)
    other = replace(target, process_id="other", pid=99, path="/other.exe")
    backend = Backend(first, second)
    coordinator = GameAudioCoordinator(backend)
    coordinator.update_targets((target, other))
    observations = coordinator.reconcile(42)
    assert [item.policy_muted for item in observations] == [False, True]
    assert [item.audible for item in observations] == [True, False]
    assert not target.user_muted and not other.user_muted
    coordinator.reconcile(99)
    assert first.muted and not second.muted
    coordinator.reconcile(None)
    assert first.muted and second.muted


def test_manual_mute_and_zero_volume_survive_focus_changes_and_policy_disable(target):
    session = Session()
    coordinator = GameAudioCoordinator(Backend(session))
    muted_target = replace(target, user_muted=True, user_volume=0)
    coordinator.update_targets((muted_target,))
    assert coordinator.reconcile(42)[0].audible is False
    coordinator.reconcile(None)
    observation = coordinator.reconcile(42, background_mute=False)[0]
    assert session.muted and session.level == 0
    assert not observation.policy_muted and not observation.audible
    coordinator.update_targets((replace(muted_target, user_muted=False),))
    observation = coordinator.reconcile(42)[0]
    assert session.muted is False and observation.audible is False


def test_all_sessions_and_endpoints_apply_late_sessions_without_touching_other_apps(target):
    first = Session()
    unrelated = Session(pid=777)
    backend = Backend(first, unrelated)
    coordinator = GameAudioCoordinator(backend)
    coordinator.update_targets((replace(target, user_volume=30),))
    coordinator.reconcile(None)
    second = Session(instance="two", endpoint="headphones")
    backend.sessions.append(second)
    observations = coordinator.reconcile(None)
    assert observations[0].available and observations[0].audible is False
    assert first.level == second.level == 0.3 and first.muted and second.muted
    assert unrelated.writes == []
    assert first.writes == [("volume", 0.3), ("mute", True)]
    assert second.writes == [("volume", 0.3), ("mute", True)]
    assert backend.enumerations == 2


def test_default_volume_applies_only_initially_on_new_sessions_or_explicit_change(target):
    session = Session()
    coordinator = GameAudioCoordinator(Backend(session))
    coordinator.update_targets((replace(target, user_volume=50),))
    coordinator.reconcile(42)
    session.level = 0.2  # 타 클라이언트의 실제 음량 조정은 주기적으로 덮어쓰지 않는다.
    coordinator.reconcile(None)
    assert session.level == 0.2
    coordinator.update_targets((replace(target, user_volume=75),))
    coordinator.reconcile(42)
    assert session.level == 0.75
    assert [write for write in session.writes if write[0] == "volume"] == [
        ("volume", 0.5), ("volume", 0.75),
    ]


def test_audible_is_calculated_per_actual_session_after_requested_writes(target):
    # max(volume) + all(muted) 조합은 이 두 무음 세션을 유음으로 오판한다.
    first = Session(level=1.0, muted=True)
    second = Session(instance="two", level=0.0, muted=False)
    first.ignore_mute = True  # 요청 성공이 실제 상태 변경을 뜻하지 않는 경우도 실제값을 읽는다.
    coordinator = GameAudioCoordinator(Backend(first, second))
    coordinator.update_targets((target,))
    observation = coordinator.reconcile(42)[0]
    assert observation.available and observation.volume == 1.0
    assert observation.muted is False and observation.audible is False


def test_missing_session_is_unknown_then_late_session_is_applied(target):
    backend = Backend()
    coordinator = GameAudioCoordinator(backend)
    coordinator.update_targets((target,))
    missing = coordinator.reconcile(42)[0]
    assert not missing.available and missing.audible is None
    backend.sessions.append(Session())
    assert coordinator.reconcile(None)[0].audible is False


def test_partial_failure_is_unknown_and_other_sessions_still_apply(target, caplog):
    broken, healthy = Session(), Session(instance="healthy")
    broken.fail_write = True
    coordinator = GameAudioCoordinator(Backend(broken, healthy))
    coordinator.update_targets((target,))
    observation = coordinator.reconcile(None)[0]
    assert not observation.available and observation.audible is None
    assert observation.volume is None and observation.muted is None
    assert healthy.muted
    assert "세션 적용/조회 실패" in caplog.text


def test_enumeration_failure_does_not_claim_quiet_or_drop_cleanup_targets(target, caplog):
    backend = Backend(Session())
    coordinator = GameAudioCoordinator(backend)
    coordinator.update_targets((target,))
    coordinator.reconcile(None)
    backend.error = OSError("audio service unavailable")
    assert coordinator.reconcile(42)[0].audible is None
    assert coordinator.cleanup() is False
    assert "세션 열거 실패" in caplog.text
    backend.error = None
    assert coordinator.cleanup() and not backend.sessions[0].muted


def test_removed_target_restores_latest_user_setting_on_next_reconcile(target):
    session = Session()
    coordinator = GameAudioCoordinator(Backend(session))
    coordinator.update_targets((target,))
    coordinator.reconcile(None)
    assert session.muted
    coordinator.update_targets(())
    assert coordinator.reconcile(None) == ()
    assert session.muted is False


def test_cleanup_uses_latest_manual_default_and_preserves_volume(target):
    session = Session()
    coordinator = GameAudioCoordinator(Backend(session))
    coordinator.update_targets((target,))
    coordinator.reconcile(None)
    coordinator.update_targets((replace(target, user_muted=True),))
    assert coordinator.cleanup()
    assert session.muted and session.level == 0.8


def test_pid_identity_change_prevents_policy_and_cleanup_writes(target):
    session = Session()
    backend = Backend(session)
    backend.valid = False
    coordinator = GameAudioCoordinator(backend)
    coordinator.update_targets((target,))
    assert coordinator.reconcile(None)[0].available is False
    assert coordinator.cleanup() and session.writes == []


def test_failed_removed_target_restore_is_retained_for_cleanup(target):
    session = Session()
    coordinator = GameAudioCoordinator(Backend(session))
    coordinator.update_targets((target,))
    coordinator.reconcile(None)
    session.fail_write = True
    coordinator.update_targets(())
    coordinator.reconcile(None)
    assert coordinator.cleanup() is False
    session.fail_write = False
    assert coordinator.cleanup() and not session.muted


def test_cleanup_restores_other_sessions_even_if_one_session_is_broken(target):
    broken, healthy = Session(), Session(instance="healthy")
    coordinator = GameAudioCoordinator(Backend(broken, healthy))
    coordinator.update_targets((target,))
    coordinator.reconcile(None)
    broken.fail_write = True
    assert coordinator.cleanup() is False
    assert broken.muted and healthy.muted is False
    broken.fail_write = False
    assert coordinator.cleanup() and broken.muted is False


def test_cleanup_does_not_claim_success_when_actual_mute_did_not_restore(target):
    session = Session()
    coordinator = GameAudioCoordinator(Backend(session))
    coordinator.update_targets((target,))
    coordinator.reconcile(None)
    session.ignore_mute = True
    assert coordinator.cleanup() is False
    assert session.muted


@pytest.mark.parametrize("change", ["created", "path", "user", "running"])
def test_native_identity_reuses_existing_user_session_boundary(monkeypatch, target, change):
    import psutil
    from src.core import process_monitor
    state = SimpleNamespace(created=123.0, path="/game.exe", user=True, running=True)
    process = SimpleNamespace(
        is_running=lambda: state.running, create_time=lambda: state.created, exe=lambda: state.path,
    )
    monkeypatch.setattr(psutil, "Process", lambda _pid: process)
    monkeypatch.setattr(process_monitor, "_belongs_to_current_user_session", lambda _proc: state.user)
    assert audio_control.verify_identity(target)
    setattr(state, change, {"created": 999.0, "path": "/other.exe", "user": False, "running": False}[change])
    assert not audio_control.verify_identity(target)


def test_native_enumeration_uses_all_active_render_devices_and_skips_system_expired(monkeypatch):
    simple, control2, manager2 = object(), object(), SimpleNamespace(_iid_="manager")
    def collection(items):
        return SimpleNamespace(GetCount=lambda: len(items), Item=lambda index: items[index])
    def control(pid, instance, state=1):
        volume = SimpleNamespace(GetMasterVolume=lambda: 0.7, GetMute=lambda: False)
        item = SimpleNamespace(GetProcessId=lambda: pid, GetState=lambda: state,
                               GetSessionInstanceIdentifier=lambda: instance)
        item.QueryInterface = lambda interface: volume if interface is simple else item
        return item
    def device(endpoint, controls):
        enumerator = SimpleNamespace(GetCount=lambda: len(controls), GetSession=lambda index: controls[index])
        manager = SimpleNamespace(GetSessionEnumerator=lambda: enumerator)
        manager.QueryInterface = lambda _interface: manager
        return SimpleNamespace(GetId=lambda: endpoint, Activate=lambda *_args: manager)
    devices = collection([
        device("speakers", [control(42, "one"), control(0, "system"), control(42, "expired", 2)]),
        device("headphones", [control(42, "two")]),
    ])
    calls = []
    native = SimpleNamespace(EnumAudioEndpoints=lambda flow, state: calls.append((flow, state)) or devices)
    module = SimpleNamespace(AudioUtilities=SimpleNamespace(GetDeviceEnumerator=lambda: native),
                             ISimpleAudioVolume=simple, IAudioSessionControl2=control2,
                             IAudioSessionManager2=manager2)
    monkeypatch.setitem(sys.modules, "comtypes", SimpleNamespace(CLSCTX_ALL=23))
    monkeypatch.setitem(sys.modules, "pycaw", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "pycaw.pycaw", module)
    sessions = audio_control.enumerate_sessions()
    assert calls == [(0, 1)]
    assert [session.key for session in sessions] == [("speakers", "one"), ("headphones", "two")]
    assert all(session.pid == 42 and session.get_volume() == 0.7 for session in sessions)


def test_legacy_public_functions_aggregate_and_write_all_matching_pid_sessions(monkeypatch):
    first, second, unrelated = Session(level=0.2, muted=True), Session(level=0.8), Session(pid=99)
    def legacy(session):
        volume = SimpleNamespace(
            GetMasterVolume=session.get_volume, GetMute=session.get_mute,
            SetMasterVolume=lambda level, _context: session.set_volume(level),
            SetMute=lambda mute, _context: session.set_mute(mute),
        )
        return SimpleNamespace(Process=SimpleNamespace(pid=session.pid),
                               _ctl=SimpleNamespace(QueryInterface=lambda _interface: volume))
    module = SimpleNamespace(AudioUtilities=SimpleNamespace(GetAllSessions=lambda: [
        legacy(first), legacy(second), legacy(unrelated),
    ]), ISimpleAudioVolume=object())
    monkeypatch.setitem(sys.modules, "pycaw", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "pycaw.pycaw", module)
    assert audio_control.get_app_volume(42) == 0.8
    assert audio_control.is_muted(42) is False
    assert audio_control.set_app_volume(42, 2.0) and audio_control.set_mute(42, True)
    assert first.level == second.level == 1.0 and first.muted and second.muted
    assert unrelated.writes == []
    assert audio_control.get_app_volume(123) is None
    assert audio_control.is_muted(123) is None
    assert audio_control.set_mute(123, True) is False


def test_no_game_targets_need_no_audio_enumeration_or_restore():
    class UnavailableDevice:
        def enumerate_sessions(self):
            raise AssertionError("대상이 없으면 오디오 장치에 접근하지 않아야 한다")

    coordinator = GameAudioCoordinator(UnavailableDevice())
    assert coordinator.reconcile(None) == ()
    assert coordinator.cleanup()
