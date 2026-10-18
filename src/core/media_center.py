"""로그온 사용자 worker 하나에서 게임 오디오·포커스·미디어를 연결한다.

생성/설정/조회는 OS I/O가 없다. 명시적 start 이후에만 Windows 객체를 만들고,
stop은 새 명령을 먼저 차단한 뒤 같은 worker에서 임시 음소거를 정리한다.
"""
from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, replace
import logging
import os
import sys
import threading
import time

from src.core.game_audio import GameAudioCoordinator, GameAudioObservation, GameAudioTarget
from src.core.game_focus import AutoFocusTracker, WindowsGameFocusNative
from src.core.media_policy import BgmPolicy
from src.core.media_sessions import (
    MediaSessionInfo, WindowsMediaSessions, is_spotify_session,
)
from src.core.spotify_app import SpotifyWindow, close_spotify_window, launch_spotify, spotify_processes, spotify_window
from src.core.spotify_audio import SpotifyAudioController, SpotifyAudioSnapshot

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MediaOptions:
    auto_bgm: bool = True
    background_mute: bool = True
    auto_focus: bool = True


@dataclass(frozen=True)
class MediaCenterSnapshot:
    sessions: tuple[MediaSessionInfo, ...] = ()
    bgm_session_id: str | None = None
    options: MediaOptions = MediaOptions()
    media_hold: bool = False
    error: str = ""
    game_audio: tuple[GameAudioObservation, ...] = ()
    running: bool = False
    spotify_audio: SpotifyAudioSnapshot = SpotifyAudioSnapshot()


@dataclass(frozen=True)
class _Request:
    action: str
    session_id: str | None
    epoch: int
    value: int | bool | None = None


@dataclass(frozen=True)
class _PendingPreparation:
    generation: int
    deadline: float
    intent: str
    automatic: bool
    session_id: str | None = None
    background_started_at: float | None = None
    play_requested: bool = False
    background_window: tuple[SpotifyWindow, float] | None = None


class MediaCenterRuntime:
    """callback은 worker에서 호출한다. GUI 호출자는 Qt signal로 넘겨야 한다.

    request의 bool은 큐 접수 여부이며 실제 재생 성공을 뜻하지 않는다. native
    snapshot/control은 직렬 처리하지만 await 중에도 게임 오디오 관측은 계속한다.
    """

    POLL_SECONDS = 0.25
    IO_TIMEOUT_SECONDS = 1.0
    PREPARE_TIMEOUT_SECONDS = 60.0
    BACKGROUND_CLOSE_DELAY_SECONDS = 5.0

    def __init__(self, on_change=None, *, backend_factory=WindowsMediaSessions,
                 audio_factory=GameAudioCoordinator, focus_factory=AutoFocusTracker,
                 native_factory=WindowsGameFocusNative, spotify_launcher=launch_spotify,
                 dj_launcher=None, spotify_opener=None, spotify_process_reader=spotify_processes,
                 spotify_audio_factory=SpotifyAudioController,
                 spotify_window_reader=spotify_window, spotify_window_closer=close_spotify_window):
        self._on_change = on_change
        self._backend_factory = backend_factory
        self._audio_factory = audio_factory
        self._focus_factory = focus_factory
        self._native_factory = native_factory
        self._spotify_launcher = spotify_launcher
        self._dj_launcher = dj_launcher if dj_launcher is not None else lambda: launch_spotify(dj=True)
        self._spotify_opener = spotify_opener if spotify_opener is not None else lambda: launch_spotify(show_window=True)
        self._spotify_process_reader = spotify_process_reader
        self._spotify_audio_factory = spotify_audio_factory
        self._spotify_window_reader = spotify_window_reader
        self._spotify_window_closer = spotify_window_closer
        self._lock = threading.Lock()
        self._thread = None
        self._loop = None
        self._main_task = None
        self._wake = None
        self._stop = threading.Event()
        self._targets: tuple[GameAudioTarget, ...] = ()
        self._options = MediaOptions()
        self._requests: deque[_Request] = deque()
        self._generation = 0
        self._epoch = 0
        self._snapshot = MediaCenterSnapshot()
        self._cleanup_ok = True

    @property
    def snapshot(self) -> MediaCenterSnapshot:
        with self._lock:
            return self._snapshot

    @property
    def running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def start(self, options: MediaOptions = MediaOptions()) -> bool:
        # 두 라이브러리의 최초 import는 호출 스레드를 STA로 초기화한다.
        # 명시적으로 활성화하는 GUI 스레드에서 먼저 로드하고 worker는 MTA로 유지한다.
        try:
            if sys.platform == "win32":
                import pythoncom  # noqa: F401
                import comtypes  # noqa: F401
        except Exception as exc:
            logger.exception("미디어 센터 Windows 라이브러리 준비 실패")
            with self._lock:
                self._snapshot = MediaCenterSnapshot(
                    options=options, error=f"Windows 미디어 라이브러리 준비 실패: {exc}")
            return False
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return True
            self._options = options
            self._generation += 1
            self._epoch += 1
            self._requests.clear()
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._thread_main, name="HomeworkHelperMedia", daemon=True)
            self._thread.start()
        return True

    def update_targets(self, targets: tuple[GameAudioTarget, ...]) -> None:
        with self._lock:
            self._targets = tuple(targets)
        self._notify_worker()

    def configure(self, options: MediaOptions) -> bool:
        with self._lock:
            if self._stop.is_set():
                return False
            if options == self._options:
                return True
            self._options = options
        self._notify_worker()
        return True

    def request(self, action: str, session_id: str | None = None, *, value=None) -> bool:
        if action not in {"open", "prepare", "select", "play", "pause", "previous", "next", "dj", "volume", "mute"}:
            return False
        if action == "select" and not session_id:
            return False
        if action == "volume" and (type(value) is not int or not 0 <= value <= 100):
            return False
        if action == "mute" and type(value) is not bool:
            return False
        if action not in {"volume", "mute"} and value is not None:
            return False
        if action in {"open", "dj", "volume", "mute"} and session_id is not None:
            return False
        with self._lock:
            if self._stop.is_set() or self._thread is None or not self._thread.is_alive():
                return False
            request = _Request(action, session_id, self._epoch, value)
            if action in {"prepare", "play", "dj"} and self._requests and request == self._requests[-1]:
                return True
            if action in {"pause", "select", "previous", "next"}:
                self._generation += 1
            self._requests.append(request)
        self._notify_worker()
        return True

    def stop(self, timeout_seconds: float = 2) -> bool:
        with self._lock:
            was_stopping = self._stop.is_set()
            self._stop.set()  # command gate closes before attempting to join
            self._generation += 1
            self._requests.clear()
            thread, loop, task = self._thread, self._loop, self._main_task
        if not was_stopping and loop is not None and task is not None:
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:
                pass
        if thread is None:
            return True
        if thread is threading.current_thread():
            return False
        thread.join(max(0, timeout_seconds))
        return not thread.is_alive() and self._cleanup_ok

    def _notify_worker(self):
        with self._lock:
            loop, wake = self._loop, self._wake
        if loop is not None and wake is not None:
            try:
                loop.call_soon_threadsafe(wake.set)
            except RuntimeError:
                pass

    def _inputs(self):
        with self._lock:
            return self._targets, self._options, self._generation

    def _publish(self):
        snapshot = MediaCenterSnapshot(
            self._sessions, self._selected, self._inputs()[1],
            self._policy.media_hold, self._error, self._observations,
            not self._stop.is_set(),
            self._spotify_audio_state,
        )
        with self._lock:
            if snapshot == self._snapshot:
                return
            self._snapshot = snapshot
        if self._on_change is not None:
            try:
                self._on_change(snapshot)
            except Exception:
                logger.exception("미디어 상태 수신자 오류")

    def _failure(self, message, source="command"):
        if message != self._error:
            logger.warning("미디어 센터: %s", message)
        self._error = message
        self._error_source = source

    def _clear_error(self, source):
        if self._error_source == source:
            self._error = ""
            self._error_source = None

    def _thread_main(self):
        uninitialize = None
        self._cleanup_ok = True
        self._sessions = ()
        self._selected = None
        self._explicit_selection = None
        self._observations = ()
        self._game_audible = None
        self._error = ""
        self._error_source = None
        self._pending = None
        self._spotify_audio_state = SpotifyAudioSnapshot()
        self._policy = BgmPolicy()
        loop = asyncio.new_event_loop()
        try:
            if sys.platform == "win32":
                import pythoncom
                pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
                uninitialize = pythoncom.CoUninitialize
            asyncio.set_event_loop(loop)
            with self._lock:
                self._loop = loop
                self._wake = asyncio.Event()
                self._main_task = loop.create_task(self._run())
            loop.run_until_complete(self._main_task)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self._cleanup_ok = False
            self._failure(f"미디어 센터 시작/실행 실패: {exc}")
        finally:
            self._stop.set()
            self._publish()
            with self._lock:
                self._loop = self._wake = self._main_task = None
            loop.close()
            if uninitialize is not None:
                uninitialize()

    async def _run(self):
        backend = audio = focus = None
        tasks = []
        try:
            if self._stop.is_set():
                return
            self._native = self._native_factory()
            backend = self._backend_factory()
            audio = self._audio_factory()
            focus = self._focus_factory(started_at_wall=time.time(), native=self._native)
            self._backend, self._audio, self._focus = backend, audio, focus
            self._spotify_audio = self._spotify_audio_factory()
            tasks = [asyncio.create_task(self._game_loop()),
                     asyncio.create_task(self._media_loop())]
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            if focus is not None:
                self._focus.cancel()
            if audio is not None:
                try:
                    audio.update_targets(self._inputs()[0])
                    self._cleanup_ok = audio.cleanup() is not False
                    if not self._cleanup_ok:
                        self._failure("일부 게임 음소거를 복원하지 못했습니다.")
                except Exception as exc:
                    self._cleanup_ok = False
                    self._failure(f"게임 음소거 복원 실패: {exc}")
            if backend is not None:
                try:
                    backend.close()
                except Exception as exc:
                    self._cleanup_ok = False
                    self._failure(f"미디어 연결 정리 실패: {exc}")

    async def _game_loop(self):
        last_external = None
        autofocus = self._inputs()[1].auto_focus
        while not self._stop.is_set():
            targets, options, _ = self._inputs()
            try:
                raw_pid, raw_hwnd = self._native.foreground()
                known = bool(raw_pid and raw_hwnd)
                if known and raw_pid != os.getpid():
                    last_external = (raw_pid, raw_hwnd)
                effective = last_external if raw_pid == os.getpid() or not known else (raw_pid, raw_hwnd)
                foreground_pid = effective[0] if effective else None
                self._audio.update_targets(targets)
                self._observations = self._audio.reconcile(
                    foreground_pid,
                    background_mute=options.background_mute and foreground_pid is not None,
                )
                current = next((item for item in self._observations
                                if item.target.pid == foreground_pid), None)
                audible = (current.audible if current.available else None) if current else False
                # 비활성 게임의 자동 음소거도 확인돼야 전체가 조용하다고 판단할 수 있다.
                if options.background_mute:
                    if any(item.available and item.audible is True for item in self._observations):
                        audible = True
                    elif any(not item.available or item.audible is None for item in self._observations):
                        audible = None
                self._game_audible = audible if known and effective else None
                if options.auto_focus and not autofocus:
                    self._focus = self._focus_factory(started_at_wall=time.time(), native=self._native)
                autofocus = options.auto_focus
                if autofocus:
                    self._focus.tick(targets, raw_pid, raw_hwnd, time.monotonic(), os.getpid())
                else:
                    self._focus.cancel()
                self._clear_error("game")
            except Exception as exc:
                self._game_audible = None
                self._failure(f"게임 오디오/포커스 관측 실패: {exc}", "game")
            self._publish()
            await asyncio.sleep(self.POLL_SECONDS)

    def _select_bgm(self):
        spotify = tuple(item for item in self._sessions if is_spotify_session(item))
        if self._explicit_selection is not None:
            self._selected = next((item.session_id for item in spotify
                                   if item.session_id == self._explicit_selection), None)
            if self._selected is None:
                self._failure("선택한 Spotify 세션이 종료되었습니다. 다시 선택해 주세요.", "selection")
            else:
                self._clear_error("selection")
        elif len(spotify) == 1:
            self._selected = spotify[0].session_id
            self._clear_error("selection")
        else:
            self._selected = None
            if len(spotify) > 1:
                self._failure("Spotify 세션이 여러 개입니다. BGM 대상을 선택해 주세요.", "selection")
            else:
                self._clear_error("selection")

    async def _media_loop(self):
        while not self._stop.is_set():
            self._wake.clear()
            _, options, generation = self._inputs()
            self._policy.set_enabled(options.auto_bgm)
            observed_pending = self._pending
            try:
                self._sessions = tuple(await asyncio.wait_for(
                    self._backend.snapshot(), self.IO_TIMEOUT_SECONDS))
                self._clear_error("observation")
                valid = True
                self._select_bgm()
            except Exception as exc:
                self._failure(f"미디어 상태 조회 실패: {exc}", "observation")
                valid = False
            other_playing = any(item.status == "playing" and item.session_id != self._selected
                                for item in self._sessions)
            selected = next((item for item in self._sessions if item.session_id == self._selected), None)
            automatic = self._policy.observe(
                game_audible=self._game_audible, other_playing=other_playing,
                bgm_playing=selected is not None and selected.status == "playing",
            ) if valid else None
            with self._lock:
                commands = tuple(self._requests)
                self._requests.clear()
            fresh = True
            for command in commands:
                if self._stop.is_set():
                    break
                if command.epoch == self._epoch:
                    await self._execute(command, valid, fresh=fresh)
                    if command.action in {"play", "pause", "previous", "next", "dj"}:
                        fresh = False
            policy_commands = any(command.action not in {"open", "prepare", "volume", "mute"} for command in commands)
            if not policy_commands and automatic is not None and not self._stop.is_set():
                if automatic == "pause" and self._selected is not None:
                    await self._control(self._selected, "pause", generation, automatic=True)
                elif automatic == "play":
                    await self._play(automatic=True, generation=generation)
            # URI 실행·의도 변경 이전에 얻은 세션 관측으로 새 준비를 완료하지 않는다.
            if not self._stop.is_set():
                # 같은 cycle의 자동 Play가 준비를 만들었어도 사용자가 연 창은 닫지 않는다.
                if self._pending is not None and any(command.action == "open" and command.epoch == self._epoch for command in commands):
                    self._pending = replace(self._pending, background_started_at=None, background_window=None)
                observed_current = self._pending is observed_pending
                self._close_pending_window(valid and observed_current)
                await self._advance_pending(valid and observed_current)
            self._refresh_spotify_audio()
            self._publish()
            try:
                await asyncio.wait_for(self._wake.wait(), self.POLL_SECONDS)
            except asyncio.TimeoutError:
                pass

    async def _execute(self, command, valid, *, fresh=True):
        action, session_id = command.action, command.session_id
        if action == "open":
            try:
                if not self._spotify_opener():
                    raise RuntimeError("Spotify 창 열기 요청이 거부되었습니다.")
                self._clear_error("spotify_open")
            except Exception as exc:
                self._failure(f"Spotify 창 열기 실패: {exc}", "spotify_open")
            return
        if action in {"volume", "mute"}:
            try:
                method = self._spotify_audio.set_volume if action == "volume" else self._spotify_audio.set_mute
                if not method(command.value):
                    self._failure("Spotify 음량·음소거가 실제로 적용됐는지 확인하지 못했습니다.", "spotify_audio_control")
                else:
                    self._clear_error("spotify_audio_control")
            except Exception as exc:
                self._failure(f"Spotify 음량·음소거 제어 실패: {exc}", "spotify_audio_control")
            return
        if action == "prepare":
            self._prepare("prepare", automatic=False, generation=self._inputs()[2])
            return
        if action in {"pause", "select", "previous", "next"}:
            cancelled = self._pending is not None
            self._pending = None
        else:
            cancelled = False
        if action == "select":
            if any(item.session_id == session_id and is_spotify_session(item) for item in self._sessions):
                self._explicit_selection = session_id
                self._select_bgm()
            else:
                self._failure("선택한 Spotify 세션을 찾을 수 없습니다.")
            return
        if not valid:
            self._failure("최신 미디어 상태를 확인하지 못해 제어하지 않았습니다.")
            return
        if action == "dj":
            self._policy.manual_play()
            self._prepare("dj", automatic=False, generation=self._inputs()[2])
            return
        if action == "play" and (session_id is None or session_id == self._selected):
            self._policy.manual_play()
            await self._play(automatic=False, generation=self._inputs()[2], session_id=session_id, fresh=fresh)
            return
        target_id = session_id or self._selected
        if target_id is None:
            if action == "pause" and cancelled:
                return
            self._failure("제어할 미디어 세션이 없습니다.")
            return
        await self._control(target_id, action)

    def _refresh_spotify_audio(self):
        try:
            self._spotify_audio_state = self._spotify_audio.snapshot()
            self._clear_error("spotify_audio_observation")
        except Exception as exc:
            self._spotify_audio_state = SpotifyAudioSnapshot()
            self._failure(f"Spotify 실제 음량·음소거 조회 실패: {exc}", "spotify_audio_observation")

    def _launch(self, *, dj=False):
        if self._stop.is_set():
            return False
        try:
            if not (self._dj_launcher if dj else self._spotify_launcher)():
                raise RuntimeError("Spotify URI 요청이 거부되었습니다.")
            self._clear_error("command")
            return True
        except Exception as exc:
            self._failure(f"Spotify 준비 실패: {exc}")
            return False

    def _prepare(self, intent, *, automatic, generation, session_id=None):
        if self._stop.is_set() or generation != self._inputs()[2]:
            return
        pending = self._pending
        if pending is not None and pending.generation != generation:
            self._pending = pending = None
        if pending is not None:
            if intent == "prepare":
                return  # prepare는 기존 재생 의도와 최초 deadline을 바꾸지 않는다.
            dj_requested = intent == "dj" and pending.intent != "dj"
            merged = "dj" if intent == "dj" or pending.intent == "dj" else "play"
            updated = replace(pending, intent=merged,
                              automatic=automatic if pending.intent == "prepare" else pending.automatic and automatic,
                              session_id=session_id or pending.session_id,
                              play_requested=False if dj_requested else pending.play_requested)
            self._pending = pending if updated == pending else updated
            if dj_requested and not self._launch(dj=True):
                self._pending = None
            return
        if intent == "prepare" and any(is_spotify_session(item) for item in self._sessions):
            self._clear_error("command")
            return
        try:
            running = self._selected is not None or bool(self._spotify_process_reader())
        except Exception as exc:
            self._failure(f"Spotify 실행 상태 조회 실패: {exc}")
            return  # 조회 오류를 미실행으로 바꿔 URI를 중복 실행하지 않는다.
        if self._stop.is_set() or generation != self._inputs()[2]:
            return
        dj = intent == "dj" or (intent == "play" and not running and self._selected is None)
        actual_intent = "dj" if dj else intent
        cold = not running and self._selected is None
        self._pending = _PendingPreparation(generation, time.monotonic() + self.PREPARE_TIMEOUT_SECONDS,
                                            actual_intent, automatic, session_id,
                                            time.time() if cold else None)
        if cold or intent == "dj":
            if not self._launch(dj=dj):
                self._pending = None

    def _close_pending_window(self, valid):
        pending = self._pending
        if pending is None or pending.background_started_at is None or pending.intent == "prepare":
            return

        def current():
            with self._lock:
                opening = any(request.action == "open" and request.epoch == self._epoch for request in self._requests)
            return (not opening and not self._stop.is_set() and self._pending is pending
                    and pending.generation == self._inputs()[2]
                    and time.monotonic() < pending.deadline
                    and (not pending.automatic or self._automatic_allowed(pending.generation)))

        if not current():
            return
        if pending.session_id is not None and pending.session_id != self._selected:
            return  # 변경된 미디어 세션을 닫기 전에 기존 준비를 취소한다.
        try:
            expected = pending.background_window[0] if pending.background_window else None
            window = self._spotify_window_reader(pending.background_started_at, expected=expected)
            if not current():
                return
            if window is None:
                if expected is None:
                    return
            elif expected is None:
                self._pending = replace(pending, background_window=(window, time.monotonic()))
                return
            elif (not valid or time.monotonic() - pending.background_window[1] < self.BACKGROUND_CLOSE_DELAY_SECONDS
                  or not any(item.session_id == self._selected and is_spotify_session(item)
                             and item.status == "playing" for item in self._sessions)):
                return
            else:
                if self._spotify_window_closer(window, is_current=current):
                    logger.info("Spotify 새 창 트레이 닫기 요청 수락: PID=%s HWND=%s", window.process.pid, window.hwnd)
        except Exception:
            logger.warning("Spotify 새 창 트레이 요청 실패; 재생 준비는 계속합니다.", exc_info=True)
        if self._pending is pending:
            self._pending = replace(pending, background_started_at=None, background_window=None)

    async def _play(self, *, automatic, generation, session_id=None, fresh=True):
        if automatic and not self._automatic_allowed(generation):
            return
        if self._pending is not None:
            self._prepare("play", automatic=automatic, generation=generation, session_id=session_id)
        elif self._selected is not None:
            selected = next(item for item in self._sessions if item.session_id == self._selected)
            if selected.status == "playing" and fresh:
                self._clear_error("command")
                return
            if selected.can_play:
                await self._control(self._selected, "play", generation, automatic=automatic)
            else:
                self._prepare("play", automatic=automatic, generation=generation,
                              session_id=session_id or self._selected)
        elif any(is_spotify_session(item) for item in self._sessions):
            self._failure("BGM으로 사용할 Spotify 세션을 먼저 선택해 주세요.")
        elif self._explicit_selection is not None:
            self._failure("이전 Spotify 세션을 새 세션으로 자동 대체하지 않습니다.")
        else:
            self._prepare("play", automatic=automatic, generation=generation, session_id=session_id)

    async def _advance_pending(self, valid):
        pending = self._pending
        if pending is None:
            return
        if pending.generation != self._inputs()[2]:
            self._pending = None
        elif pending.automatic and not self._automatic_allowed(pending.generation):
            self._pending = None
        elif time.monotonic() >= pending.deadline:
            self._pending = None
            prepared = pending.intent == "prepare" and any(is_spotify_session(item) for item in self._sessions)
            if pending.play_requested or prepared:
                if pending.background_started_at is not None:
                    logger.info("Spotify 새 표시 창 관측을 마쳤습니다. 늦은 창을 닫지 않습니다.")
            else:
                self._failure("Spotify 준비 대기가 만료되었습니다. 자동 재요청하지 않습니다.")
        elif valid:
            if pending.intent == "prepare":
                if any(is_spotify_session(item) for item in self._sessions):
                    self._pending = None
                    self._clear_error("command")
                return
            selected = next((item for item in self._sessions if item.session_id == self._selected), None)
            if selected is None:
                return
            if pending.session_id is None:
                pending = replace(pending, session_id=selected.session_id)
                self._pending = pending
            if pending.session_id is not None and pending.session_id != selected.session_id:
                self._pending = None
                self._failure("미디어 세션이 변경되어 이전 재생 대기를 취소했습니다.")
            elif selected.status == "playing":
                if pending.background_started_at is None:
                    self._pending = None
                elif not pending.play_requested:
                    self._pending = replace(pending, play_requested=True)
                self._clear_error("command")
            elif pending.play_requested:
                if pending.background_started_at is None:
                    self._pending = None
            elif selected.can_play:
                self._pending = (replace(pending, play_requested=True)
                                 if pending.background_started_at is not None else None)
                await self._control(selected.session_id, "play", pending.generation, automatic=pending.automatic)

    def _automatic_allowed(self, generation):
        return (not self._stop.is_set() and self._inputs()[1].auto_bgm and generation == self._inputs()[2]
                and self._policy.permits_automatic_play(
                    game_audible=self._game_audible,
                    other_playing=any(item.status == "playing" and item.session_id != self._selected
                                      for item in self._sessions)))

    async def _control(self, session_id, action, generation=None, *, automatic=False):
        if self._stop.is_set() or (generation is not None and generation != self._inputs()[2]):
            return
        if automatic:
            allowed = self._automatic_allowed(generation) if action == "play" else self._inputs()[1].auto_bgm
            if not allowed:
                return
        if not any(item.session_id == session_id for item in self._sessions):
            self._failure("미디어 세션이 변경되어 이전 요청을 실행하지 않았습니다.")
            return
        try:
            accepted = await asyncio.wait_for(
                self._backend.control(session_id, action), self.IO_TIMEOUT_SECONDS)
            if not accepted:
                self._failure(f"미디어 앱이 {action} 요청을 수락하지 않았습니다.")
            else:
                self._clear_error("command")
        except Exception as exc:
            self._failure(f"미디어 {action} 요청 실패: {exc}")
