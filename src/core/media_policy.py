"""게임·미디어 전환에만 반응하는 BGM 정책. OS·Qt·DB에 접근하지 않는다."""
from __future__ import annotations


class BgmPolicy:
    """재생 상태를 강제 유지하지 않고 한 전환에서 최대 한 명령을 만든다.

    다른 미디어의 정지는 종료와 구분할 수 없으므로 보류를 해제하지 않는다.
    명시적 재생 또는 자동 기능을 다시 켜는 동작만 그 보류를 해제한다.
    """

    def __init__(self) -> None:
        self.enabled = False
        self.media_hold = False
        self._initial = False
        self._game_audible: bool | None = None
        self._other_playing = False

    def set_enabled(self, enabled: bool) -> None:
        if self.enabled == enabled:
            return
        self.enabled = enabled
        self._initial = enabled
        self._game_audible = None
        if enabled:
            self.media_hold = False
            self._other_playing = False

    def manual_play(self) -> None:
        self.media_hold = False
        # 사용자 play와 같은 관측 주기에 자동 play를 중복 요청하지 않는다.
        self._initial = False

    def observe(
        self, *, game_audible: bool | None, other_playing: bool, bgm_playing: bool,
    ) -> str | None:
        if not self.enabled:
            return None
        media_started = other_playing and not self._other_playing
        self._other_playing = other_playing
        if media_started:
            self.media_hold = True

        # 미준비/오류를 무음 또는 소리 전환으로 추정하지 않는다.
        if game_audible is None:
            return "pause" if media_started and bgm_playing else None

        became_audible = game_audible and (self._initial or self._game_audible is False)
        became_quiet = not game_audible and (self._initial or self._game_audible is True)
        self._game_audible = game_audible
        self._initial = False
        if media_started or became_audible:
            return "pause" if bgm_playing else None
        if became_quiet and not other_playing and not self.media_hold and not bgm_playing:
            return "play"
        return None

    def permits_automatic_play(self, *, game_audible: bool | None, other_playing: bool) -> bool:
        """준비 중이던 play를 실제 전송하기 직전에 현재 조건으로 확인한다."""
        return self.enabled and game_audible is False and not other_playing and not self.media_hold
