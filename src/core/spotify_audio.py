"""Spotify의 실제 Windows 믹서 상태를 읽고 명시적 사용자 요청만 적용한다.

미디어 worker 하나에서 직렬 호출한다. 프로세스와 출력 장치의 세션은 각 호출에서
새로 확인하며 COM 핸들·음량 사본·DB 설정을 보관하지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
import math

from src.core.spotify_app import spotify_processes
from src.utils import audio_control

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SpotifyAudioSnapshot:
    volume: int | None = None
    muted: bool | None = None
    available: bool = False


class SpotifyAudioController:
    def __init__(self, backend=None, process_reader=spotify_processes):
        self._backend = audio_control if backend is None else backend
        self._process_reader = process_reader

    def _matching_sessions(self):
        # reader는 지정 사용자/session의 Spotify identity를 소유한다. 아래 OS 검증은
        # 그 관측 이후 종료·PID 재사용이 일어났는지를 실제 접근 직전에 확인한다.
        processes = {process.pid: process for process in self._process_reader()}
        if not processes:
            return ()
        return tuple((processes[session.pid], session)
                     for session in self._backend.enumerate_sessions()
                     if session.pid in processes)

    def snapshot(self) -> SpotifyAudioSnapshot:
        levels, muted = [], []
        try:
            for process, session in self._matching_sessions():
                if not self._backend.verify_identity(process):
                    continue
                level = session.get_volume()
                if not math.isfinite(level) or not 0 <= level <= 1:
                    raise ValueError("Spotify 오디오 세션 음량 범위가 올바르지 않습니다.")
                flag = session.get_mute()
                if not self._backend.verify_identity(process):
                    continue
                levels.append(level)
                muted.append(flag)
        except Exception:
            logger.warning("Spotify 실제 음량·음소거 조회 실패", exc_info=True)
            return SpotifyAudioSnapshot()
        if not levels:
            return SpotifyAudioSnapshot()
        return SpotifyAudioSnapshot(round(max(levels) * 100), all(muted), True)

    def set_volume(self, value: int) -> bool:
        if type(value) is not int or not 0 <= value <= 100:
            return False
        return self._apply("volume", value / 100)

    def set_mute(self, value: bool) -> bool:
        if type(value) is not bool:
            return False
        return self._apply("mute", value)

    def _apply(self, action: str, value: float | bool) -> bool:
        try:
            sessions = self._matching_sessions()
        except Exception:
            logger.warning("Spotify 오디오 제어 대상 조회 실패: 동작=%s", action, exc_info=True)
            return False
        succeeded = bool(sessions)
        for process, session in sessions:
            try:
                if not self._backend.verify_identity(process):
                    succeeded = False
                    continue
                if action == "volume":
                    session.set_volume(value)
                    actual = session.get_volume()
                    applied = math.isfinite(actual) and abs(actual - value) <= 0.00001
                else:
                    session.set_mute(value)
                    applied = session.get_mute() == value
                if not applied or not self._backend.verify_identity(process):
                    succeeded = False
                    logger.warning("Spotify 오디오 적용 후 실제 상태 확인 실패: 동작=%s PID=%s",
                                   action, process.pid)
            except Exception:
                succeeded = False
                logger.warning("Spotify 오디오 세션 제어 실패: 동작=%s PID=%s",
                               action, process.pid, exc_info=True)
        return succeeded
