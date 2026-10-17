"""미디어 의도·준비 지연의 교차 순서를 검증한다. OS·오디오·DB 접근 없음."""
import pytest

from src.core.media_policy import BgmPolicy


def observe(policy, *, game=False, media=False, bgm=False):
    return policy.observe(game_audible=game, other_playing=media, bgm_playing=bgm)


def automatic_policy():
    policy = BgmPolicy()
    policy.set_enabled(True)
    return policy


@pytest.mark.parametrize("bgm_was_playing", [False, True])
def test_media_started_during_unknown_game_audio_holds_after_everything_goes_quiet(bgm_was_playing):
    policy = automatic_policy()
    assert observe(policy, game=None, media=True, bgm=bgm_was_playing) == (
        "pause" if bgm_was_playing else None
    )
    # Firefox가 일시정지/세션 제거되고 게임 오디오가 뒤늦게 준비돼도 재개하지 않는다.
    assert observe(policy, game=None) is None
    assert observe(policy, game=False) is None
    assert observe(policy, game=True) is None
    assert observe(policy, game=False) is None
    assert policy.media_hold
    assert not policy.permits_automatic_play(game_audible=False, other_playing=False)


def test_duplicate_enabled_setting_cannot_clear_media_hold():
    policy = automatic_policy()
    assert observe(policy, media=True, bgm=True) == "pause"
    assert observe(policy) is None
    for _ in range(3):
        policy.set_enabled(True)
        assert observe(policy) is None
        assert policy.media_hold


def test_current_pause_condition_is_not_a_playback_maintenance_loop():
    policy = automatic_policy()
    assert observe(policy, game=True, bgm=True) == "pause"
    # 사용자가 직접 Spotify를 다시 재생해도 같은 게임 상태는 새 자동 사건이 아니다.
    for _ in range(3):
        assert observe(policy, game=True, bgm=True) is None
    assert observe(policy, game=False, bgm=True) is None
    # 실제 다른 게임 소리 전환에는 새 일시정지 요청을 허용한다.
    assert observe(policy, game=True, bgm=True) == "pause"


def test_manual_play_clears_hold_without_duplicating_same_cycle_play():
    policy = automatic_policy()
    assert observe(policy, media=True, bgm=True) == "pause"
    assert observe(policy) is None
    policy.manual_play()
    assert not policy.media_hold
    # 수동 명령의 실제 결과가 아직 Paused여도 자동 명령을 추가하지 않는다.
    assert observe(policy, bgm=False) is None
    assert observe(policy, bgm=True) is None
    assert observe(policy, game=True, bgm=True) == "pause"
    assert observe(policy, game=False) == "play"


def test_new_media_start_after_manual_play_is_a_new_pause_trigger():
    policy = automatic_policy()
    assert observe(policy, game=None, media=True, bgm=True) == "pause"
    policy.manual_play()
    assert observe(policy, game=False, media=True, bgm=True) is None
    assert observe(policy, game=False, media=False, bgm=True) is None
    assert observe(policy, game=None, media=True, bgm=True) == "pause"
    assert policy.media_hold


@pytest.mark.parametrize("new_game,new_media", [(None, False), (True, False), (False, True)])
def test_pending_automatic_play_is_not_permitted_after_new_blocker(new_game, new_media):
    policy = automatic_policy()
    assert observe(policy) == "play"
    observe(policy, game=new_game, media=new_media)
    assert not policy.permits_automatic_play(
        game_audible=new_game, other_playing=new_media
    )


def test_pending_play_is_blocked_even_after_media_session_disappears():
    policy = automatic_policy()
    assert observe(policy) == "play"
    assert observe(policy, media=True, bgm=False) is None
    assert observe(policy, media=False, bgm=False) is None
    assert not policy.permits_automatic_play(game_audible=False, other_playing=False)


def test_explicit_reenable_rechecks_actual_media_before_issuing_play():
    policy = automatic_policy()
    assert observe(policy) == "play"
    policy.set_enabled(False)
    assert observe(policy, media=True, bgm=True) is None
    policy.set_enabled(True)
    assert observe(policy, media=True, bgm=True) == "pause"
    assert observe(policy) is None
    policy.set_enabled(False)
    policy.set_enabled(True)
    assert observe(policy) == "play"
    assert observe(policy) is None
