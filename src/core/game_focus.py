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

    def has_window(self, target: GameAudioTarget) -> bool:
        """보이는 면적 있는 PID 창의 존재만 확인한다. splash 구분은 하지 않는다."""
        if os.name != "nt":
            return False
        import win32gui
        import win32process

        found = False

        def collect(hwnd, _extra):
            nonlocal found
            try:
                if not win32gui.IsWindowVisible(hwnd):
                    return
                if win32process.GetWindowThreadProcessId(hwnd)[1] != target.pid:
                    return
                rect = (win32gui.GetWindowPlacement(hwnd)[4] if win32gui.IsIconic(hwnd)
                        else win32gui.GetWindowRect(hwnd))
                if rect[2] > rect[0] and rect[3] > rect[1]:
                    found = True
            except Exception:
                logger.debug("준비 확인 중 사라진 게임 창 제외: hwnd=%s", hwnd, exc_info=True)

        win32gui.EnumWindows(collect, None)
        return found

    def focus(self, target: GameAudioTarget) -> bool:
        from src.utils.windows import focus_managed_process_window

        return focus_managed_process_window(target.pid, target.create_time, target.path)


@dataclass(frozen=True)
class _PendingFocus:
    target: GameAudioTarget
    initial_foreground: tuple[int, int]
    deadline: float


class AutoFocusTracker:
    """worker가 순차 tick한다. 처음 본 실행 identity당 전환 요청은 최대 한 번이다.

    창이 없을 때만 제한 시간 안에서 계속 관찰한다. 준비된 창의 포커스 요청을
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
            self.cancel()
            return
        foreground = (foreground_pid, foreground_hwnd)
        if (foreground_pid not in (0, owned_pid) and foreground_hwnd
                and foreground != pending.initial_foreground):
            logger.info("사용자 창 선택으로 게임 자동 전환 취소: 등록=%s PID=%s",
                        target.process_id, target.pid)
            self.cancel()
            return
        try:
            if not self._native.has_window(target):
                return
            # Consume before the native request, including failure and exceptions.
            self.cancel()
            if not self._native.focus(target):
                logger.warning("게임 자동 전환 요청이 허용되지 않음: 등록=%s PID=%s",
                               target.process_id, target.pid)
        except Exception:
            self.cancel()
            logger.warning("게임 자동 전환 관찰 또는 요청 실패: 등록=%s PID=%s",
                           target.process_id, target.pid, exc_info=True)
