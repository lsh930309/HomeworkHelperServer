"""사용자 저장 음량과 foreground 정책을 한 WASAPI writer에서 적용한다.

로그인 사용자 worker가 생성·갱신·정리한다. DB·Qt·오디오 callback을 소유하지 않으며
native 세션 핸들은 reconcile/cleanup 안에서만 사용한다.
"""
from __future__ import annotations

from dataclasses import dataclass
import logging

from src.utils import audio_control

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class GameAudioTarget:
    process_id: str
    pid: int
    create_time: float
    path: str
    user_muted: bool
    user_volume: int | None


@dataclass(frozen=True, slots=True)
class GameAudioObservation:
    target: GameAudioTarget
    available: bool
    volume: float | None
    muted: bool | None
    policy_muted: bool
    audible: bool | None


def _identity(target: GameAudioTarget) -> tuple:
    return target.process_id, target.pid, target.create_time, target.path


class GameAudioCoordinator:
    def __init__(self, backend=None) -> None:
        self._backend = audio_control if backend is None else backend
        self._targets: tuple[GameAudioTarget, ...] = ()
        self._retired: dict[tuple, GameAudioTarget] = {}
        self._session_volumes: dict[tuple, int | None] = {}

    def update_targets(self, targets: tuple[GameAudioTarget, ...]) -> None:
        current = {_identity(target) for target in targets}
        for target in self._targets:
            if _identity(target) not in current:
                self._retired[_identity(target)] = target
        for identity in current:
            self._retired.pop(identity, None)
        self._targets = tuple(targets)

    def _restore(self, targets, sessions) -> bool:
        succeeded = True
        for target in targets:
            try:
                if not self._backend.verify_identity(target):
                    continue
            except Exception:
                succeeded = False
                logger.warning("게임 사용자 음소거 복원 identity 조회 실패: 등록=%s PID=%s",
                               target.process_id, target.pid, exc_info=True)
                continue
            for session in sessions:
                if session.pid != target.pid:
                    continue
                try:
                    if not self._backend.verify_identity(target):
                        break
                    if session.get_mute() != target.user_muted:
                        session.set_mute(target.user_muted)
                    if session.get_mute() != target.user_muted:
                        raise RuntimeError("사용자 음소거 복원 뒤 실제 상태가 일치하지 않습니다.")
                except Exception:
                    succeeded = False
                    logger.warning("게임 사용자 음소거 복원 실패: 등록=%s PID=%s 세션=%s",
                                   target.process_id, target.pid, session.key, exc_info=True)
        return succeeded

    def reconcile(
        self, foreground_pid: int | None, *, background_mute: bool = True,
    ) -> tuple[GameAudioObservation, ...]:
        try:
            sessions = tuple(self._backend.enumerate_sessions())
        except Exception:
            logger.warning("게임 오디오 세션 열거 실패", exc_info=True)
            return tuple(GameAudioObservation(
                target, False, None, None,
                bool(background_mute and target.pid != foreground_pid), None,
            ) for target in self._targets)

        if self._retired and self._restore(tuple(self._retired.values()), sessions):
            self._retired.clear()
        observations = []
        live_volume_keys = set()
        for target in self._targets:
            policy_muted = bool(background_mute and target.pid != foreground_pid)
            levels, muted_values = [], []
            available = True
            try:
                identity_valid = self._backend.verify_identity(target)
                if not identity_valid:
                    logger.warning("게임 오디오 identity 변경 또는 종료: 등록=%s PID=%s",
                                   target.process_id, target.pid)
                    available = False
                for session in sessions if identity_valid else ():
                    if session.pid != target.pid:
                        continue
                    key = (_identity(target), session.key)
                    live_volume_keys.add(key)
                    try:
                        if not self._backend.verify_identity(target):
                            raise RuntimeError("게임 프로세스 identity가 오디오 적용 전에 변경되었습니다.")
                        if key not in self._session_volumes or self._session_volumes[key] != target.user_volume:
                            if target.user_volume is not None:
                                level = max(0, min(100, target.user_volume)) / 100.0
                                if session.get_volume() != level:
                                    session.set_volume(level)
                            self._session_volumes[key] = target.user_volume
                        desired_muted = target.user_muted or policy_muted
                        if session.get_mute() != desired_muted:
                            session.set_mute(desired_muted)
                        levels.append(session.get_volume())
                        muted_values.append(session.get_mute())
                    except Exception:
                        available = False
                        logger.warning("게임 오디오 세션 적용/조회 실패: 등록=%s PID=%s 세션=%s",
                                       target.process_id, target.pid, session.key, exc_info=True)
            except Exception:
                available = False
                logger.warning("게임 오디오 identity 조회 실패: 등록=%s PID=%s",
                               target.process_id, target.pid, exc_info=True)
            available = available and bool(levels)
            observations.append(GameAudioObservation(
                target, available, max(levels) if available else None,
                all(muted_values) if available else None, policy_muted,
                any(level > 0 and not muted for level, muted in zip(levels, muted_values))
                if available else None,
            ))
        self._session_volumes = {
            key: value for key, value in self._session_volumes.items() if key in live_volume_keys
        }
        return tuple(observations)

    def cleanup(self) -> bool:
        try:
            sessions = tuple(self._backend.enumerate_sessions())
        except Exception:
            logger.warning("게임 음소거 정리 중 세션 열거 실패", exc_info=True)
            return False
        targets = dict(self._retired)
        targets.update((_identity(target), target) for target in self._targets)
        if not self._restore(tuple(targets.values()), sessions):
            return False
        self._retired.clear()
        self._targets = ()
        self._session_volumes.clear()
        return True
