"""새 게임 창을 기다린 뒤 한 번만 전환하고 사용자의 다른 선택을 존중한다."""
from __future__ import annotations

from dataclasses import dataclass
import logging
import os

from src.core.game_audio import GameAudioTarget

logger = logging.getLogger(__name__)


def _identity(target: GameAudioTarget) -> tuple:
    return target.process_id, target.pid, target.create_time, target.path


class WindowsGameFocusNative:
    """조회는 읽기 전용이며 전환은 기존의 identity 검증 helper가 소유한다."""

    def foreground(self) -> tuple[int, int]:
        if os.name != "nt":
            return 0, 0
        import win32gui
        import win32process

        hwnd = win32gui.GetForegroundWindow()
        return (int(win32process.GetWindowThreadProcessId(hwnd)[1]), int(hwnd)) if hwnd else (0, 0)

    def window(self, target: GameAudioTarget) -> int | None:
        from src.utils.windows import managed_process_window

        return managed_process_window(target.pid, target.create_time, target.path)

    def is_related_foreground(self, target: GameAudioTarget, pid: int) -> bool:
        """현재 같은 사용자 세션의 실제 자식 계보만 준비 흐름으로 인정한다."""
        if os.name != "nt" or pid <= 0:
            return False
        import psutil
        from src.utils.audio_control import verify_identity
        from src.core.process_monitor import _belongs_to_current_user_session

        try:
            if not verify_identity(target):
                return False
            current = psutil.Process(pid)
            if not _belongs_to_current_user_session(current):
                return False
            child_created = current.create_time()
            for parent in current.parents():
                created = parent.create_time()
                if created > child_created:
                    return False  # 부모 PID가 자식 생성 뒤 재사용된 경우를 제외한다.
                if parent.pid == target.pid:
                    return abs(created - target.create_time) <= .001
                child_created = created
        except (psutil.Error, OSError):
            logger.debug("게임 시작 자식 관계 확인 실패: PID=%s", pid, exc_info=True)
        return False

    def focus(self, target: GameAudioTarget, hwnd: int | None = None) -> bool:
        from src.utils.windows import focus_managed_process_window

        return focus_managed_process_window(target.pid, target.create_time, target.path, hwnd=hwnd)


@dataclass
class _PendingFocus:
    target: GameAudioTarget
    initial_foreground: tuple[int, int]
    deadline: float
    last_game_foreground_hwnd: int | None = None


class AutoFocusTracker:
    """worker가 순차 tick한다. 처음 본 실행 identity당 전환 요청은 최대 한 번이다.

    창 부재·임시 전경 창·자식 창 전환을 같은 120초 대기에서 관찰한다. 포커스 요청을
    Windows가 거절해도 재시도하지 않는다. baseline은 기존 게임을 활성화하지 않는다.
    """

    def __init__(self, started_at_wall: float, timeout_seconds: float = 120, native=None):
        self._started_at_wall = started_at_wall
        self._timeout_seconds = timeout_seconds
        self._native = WindowsGameFocusNative() if native is None else native
        self._seen: set[tuple] | None = None
        self._pending: _PendingFocus | None = None

    def cancel(self) -> None:
        """현재 대기를 취소하며 같은 실행을 다음 tick에 다시 등록하지 않는다."""
        self._pending = None

    def reset(self) -> None:
        """대기를 취소하고 다음 tick을 새 baseline으로 사용한다."""
        self.cancel()
        self._seen = None

    def tick(
        self, targets: tuple[GameAudioTarget, ...], foreground_pid: int,
        foreground_hwnd: int, now_monotonic: float, owned_pid: int,
    ) -> None:
        current = {_identity(target): target for target in targets}
        if self._seen is None:
            self._seen = set(current)
            return

        new_targets = [target for key, target in current.items()
                       if key not in self._seen and target.create_time > self._started_at_wall]
        self._seen.update(current)

        if self._pending is not None and _identity(self._pending.target) not in current:
            self.cancel()
        if new_targets:
            # Simultaneous detections cannot produce a chain of foreground changes.
            newest = max(new_targets, key=lambda item: (
                item.create_time, item.process_id, item.pid, item.path))
            if self._pending is None or newest.create_time >= self._pending.target.create_time:
                self._pending = _PendingFocus(
                    newest, (foreground_pid, foreground_hwnd),
                    now_monotonic + self._timeout_seconds,
                )

        pending = self._pending
        if pending is None:
            return
        target = pending.target
        if now_monotonic >= pending.deadline:
            logger.info("게임 자동 전환 대기 만료: 등록=%s PID=%s", target.process_id, target.pid)
            self.cancel()
            return
        if foreground_pid == target.pid:
            if pending.last_game_foreground_hwnd != foreground_hwnd:
                logger.info("게임 시작 전경 창 관찰: 등록=%s PID=%s hwnd=%s", target.process_id, target.pid, foreground_hwnd)
            pending.last_game_foreground_hwnd = foreground_hwnd or None
            return
        foreground = (foreground_pid, foreground_hwnd)
        try:
            if (foreground_pid not in (0, owned_pid) and foreground_hwnd
                    and foreground != pending.initial_foreground
                    and not self._native.is_related_foreground(target, foreground_pid)):
                logger.info("외부 창 전환으로 게임 자동 전환 취소: 등록=%s PID=%s",
                            target.process_id, target.pid)
                self.cancel()
                return
            hwnd = self._native.window(target)
            if hwnd is None or hwnd == pending.last_game_foreground_hwnd:
                return  # 이미 앞에 나타났던 시작 창을 다시 끌어오지 않고 교체를 관찰한다.
            # Consume before the single native request, including failure and exceptions.
            self.cancel()
            accepted = self._native.focus(target, hwnd)
            actual = self._native.foreground()
            logger.info("게임 자동 전환 결과: 등록=%s PID=%s hwnd=%s 수락=%s 실제전경=%s",
                        target.process_id, target.pid, hwnd, accepted, actual == (target.pid, hwnd))
            if not accepted:
                logger.warning("게임 자동 전환 요청이 허용되지 않음: 등록=%s PID=%s",
                               target.process_id, target.pid)
        except Exception:
            self.cancel()
            logger.warning("게임 자동 전환 관찰 또는 요청 실패: 등록=%s PID=%s",
                           target.process_id, target.pid, exc_info=True)
