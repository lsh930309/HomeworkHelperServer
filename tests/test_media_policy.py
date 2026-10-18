"""사용자 시퀀스를 독립 입력으로 검증한다. Windows/DB/외부 연결 없음."""
import pytest

from src.core.media_policy import BgmPolicy


def tick(policy, game=False, other=False, bgm=False):
    return policy.observe(game_audible=game, other_playing=other, bgm_playing=bgm)


def enabled():
    policy = BgmPolicy()
    policy.set_enabled(True)
    return policy


def test_idle_activation_plays_once_and_user_pause_is_respected():
    policy = enabled()
    assert tick(policy) == "play"
    assert tick(policy, bgm=True) is None
    assert tick(policy, bgm=False) is None
    policy.set_enabled(True)  # 설정 재적용은 새로운 트리거가 아니다.
    assert tick(policy) is None
    assert tick(policy, game=True, bgm=True) == "pause"
    assert tick(policy, game=False) == "play"  # 새로운 게임 종료
    assert tick(policy) is None


@pytest.mark.parametrize("end_state", ["paused", "stopped", "removed", "timeline_end"])
def test_media_stop_never_resumes_even_through_other_game_events(end_state):
    policy = enabled()
    assert tick(policy) == "play"
    assert tick(policy, other=True, bgm=True) == "pause"
    assert tick(policy, other=True) is None
    # 상태 이름이나 세션 존재가 아니라 현재 Playing 여부만 전달한다.
    assert tick(policy, other=False) is None
    assert tick(policy, game=True) is None
    assert tick(policy, game=False) is None
    assert policy.media_hold
    assert not policy.permits_automatic_play(game_audible=False, other_playing=False)
    policy.manual_play()
    assert not policy.media_hold
    assert tick(policy, bgm=True) is None


def test_manual_resume_during_same_media_does_not_start_pause_watchdog():
    policy = enabled()
    assert tick(policy, other=True, bgm=True) == "pause"
    policy.manual_play()
    assert tick(policy, other=True, bgm=True) is None
    tick(policy, other=False)
    assert tick(policy, other=True, bgm=True) == "pause"  # 별도 신규 미디어 시작


def test_unknown_audio_does_not_invent_transitions_or_repeat_play():
    policy = enabled()
    assert tick(policy, game=None) is None
    assert tick(policy, game=False) == "play"
    assert tick(policy, game=None) is None
    assert tick(policy, game=False) is None
    assert tick(policy, game=True, bgm=True) == "pause"
    assert tick(policy, game=None) is None
    assert tick(policy, game=False) == "play"


def test_already_playing_bgm_does_not_receive_redundant_play():
    policy = enabled()
    assert tick(policy, bgm=True) is None
    assert tick(policy, bgm=False) is None


def test_disabling_cancels_delayed_play_and_reenable_is_explicit_trigger():
    policy = enabled()
    assert tick(policy) == "play"
    policy.set_enabled(False)
    assert tick(policy, game=True, other=True, bgm=True) is None
    assert not policy.permits_automatic_play(game_audible=False, other_playing=False)
    policy.set_enabled(True)
    assert tick(policy) == "play"


def test_game_mute_and_zero_have_same_policy_without_observing_waveform():
    policy = enabled()
    assert tick(policy, game=True) is None
    assert tick(policy, game=False) == "play"
    assert tick(policy, game=False, bgm=True) is None
    assert tick(policy, game=True, bgm=True) == "pause"


def test_observation_does_not_retry_a_failed_command():
    policy = enabled()
    assert tick(policy) == "play"
    # 명령이 실패하여 실제 재생이 시작되지 않아도 같은 조건에서 재시도하지 않는다.
    assert tick(policy) is None
