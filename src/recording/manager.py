import threading
import time
import logging
from typing import Callable, Literal, Optional

from src.recording.obs_client import OBSClient

logger = logging.getLogger(__name__)

RecordingState = Literal["idle", "recording", "connecting", "obs_offline"]


class RecordingManager:
    """OBS WebSocket을 통해 녹화를 제어한다."""

    def __init__(self) -> None:
        self._client = OBSClient()
        self._state: RecordingState = "obs_offline"
        self._recording_start_time: Optional[float] = None
        self._on_state_changed: Optional[Callable[[RecordingState], None]] = None
        self._lock = threading.Lock()
        self._settings: dict = {}
        self._launch_error = ""
        self._connect_thread: Optional[threading.Thread] = None
        self._startup_requested = False
        self._client.set_on_record_state_changed(self._on_record_state_changed_from_obs)
        self._client.set_on_connection_closed(self._on_connection_closed)

    # ---------- settings ----------

    def _set_settings(self, settings) -> None:
        self._settings = {
            "enabled": getattr(settings, "recording_enabled", False),
            "host": getattr(settings, "obs_host", "localhost"),
            "port": getattr(settings, "obs_port", 4455),
            "password": getattr(settings, "obs_password", ""),
        }

    def prepare_for_startup(self, settings) -> None:
        """One app initialization trigger, independent of recording settings."""
        if self._startup_requested:
            return
        self._startup_requested = True
        self._set_settings(settings)
        self._try_connect_async(launch_requested=True, connect_requested=None)

    def apply_settings(self, settings) -> None:
        """Refresh settings without launching OBS."""
        self._set_settings(settings)
        if self._settings["enabled"] and not self._client.is_connected():
            self._try_connect_async()

    # ---------- public control ----------

    def on_recording_toggle(self) -> None:
        """TriggerDispatcher의 on_long_press에 연결."""
        state = self._get_state()
        if state == "recording":
            self.stop_recording()
        elif state == "idle":
            self.start_recording()
        elif state == "obs_offline":
            # 명시적 요청에서 권한 서비스로 실행한 뒤 녹화 시작
            self._try_connect_async(then_record=True, launch_requested=True)

    def start_recording(self) -> None:
        if not self._client.is_connected():
            self._try_connect_async(then_record=True, launch_requested=True)
            return
        self._client.start_record()

    def stop_recording(self) -> None:
        if not self._client.is_connected():
            return
        self._client.stop_record()

    def get_state(self) -> RecordingState:
        return self._get_state()

    def get_elapsed_sec(self) -> int:
        with self._lock:
            if self._recording_start_time is None:
                return 0
            return int(time.monotonic() - self._recording_start_time)

    def set_on_state_changed(self, fn: Callable[[RecordingState], None]) -> None:
        self._on_state_changed = fn

    def reconnect(self) -> None:
        """사이드바 재연결 버튼 전용 — 연결만 시도하고 녹화는 시작하지 않는다."""
        self._try_connect_async(then_record=False, launch_requested=True)

    def get_last_error(self) -> str:
        return self._launch_error or self._client.get_last_error()

    def shutdown(self) -> None:
        self._on_state_changed = None
        self._client.set_on_connection_closed(None)
        self._client.set_on_record_state_changed(None)
        self._client.disconnect()

    # ---------- internal ----------

    def _get_state(self) -> RecordingState:
        with self._lock:
            return self._state

    def _set_state(self, state: RecordingState) -> None:
        changed = False
        with self._lock:
            if self._state != state:
                self._state = state
                changed = True
                if state == "recording":
                    self._recording_start_time = time.monotonic()
                elif state != "recording":
                    self._recording_start_time = None
        callback = self._on_state_changed
        if changed and callback:
            callback(state)

    def _on_record_state_changed_from_obs(self, active: bool) -> None:
        self._set_state("recording" if active else "idle")

    def _on_connection_closed(self) -> None:
        self._set_state("obs_offline")

    def _try_connect_async(self, then_record: bool = False, launch_requested: bool = False,
                           connect_requested: Optional[bool] = True) -> None:
        with self._lock:
            active = self._connect_thread
            if active and (active.ident is None or active.is_alive()):
                return
            thread = threading.Thread(
                target=self._connect_worker,
                args=(then_record, launch_requested, connect_requested, dict(self._settings)),
                daemon=True,
            )
            self._connect_thread = thread
        self._set_state("connecting")
        thread.start()

    def _connect_worker(self, then_record: bool, launch_requested: bool,
                        connect_requested: Optional[bool], s: dict) -> None:
        self._launch_error = ""
        if launch_requested:
            from src.host_service.client import HostPrivilegeClient, PrivilegeServiceError
            try:
                result = HostPrivilegeClient().launch_obs()
                needs_connection = self._settings["enabled"] if connect_requested is None else connect_requested
                if needs_connection and not result.get("already_running"):
                    time.sleep(5)
            except PrivilegeServiceError as error:
                self._launch_error = str(error)
                logger.warning("OBS 관리자 실행 실패: %s", error)
                self._set_state("obs_offline")
                return

        if connect_requested is None:
            # App preparation ends before a connection starts. Snapshot the then-current
            # settings for this separate operation, including edits made during preparation.
            s = dict(self._settings)
            connect_requested = s["enabled"]
        if not connect_requested:
            self._set_state("obs_offline")
            return

        # 연결 시도 (최대 2회: 첫 시도 실패 시 3초 후 재시도)
        host = s.get("host", "localhost")
        port = s.get("port", 4455)
        password = s.get("password", "")
        logger.info("OBS WebSocket 연결 시도: ws://%s:%s (password=%s)", host, port, "***" if password else "<empty>")
        ok = self._client.connect(host=host, port=port, password=password)
        if not ok:
            logger.warning("OBS WebSocket 1차 연결 실패, 3초 후 재시도...")
            time.sleep(3)
            ok = self._client.connect(host=host, port=port, password=password)

        if ok:
            logger.info("OBS WebSocket 연결 성공")
            self._set_state("idle")
            if then_record:
                self.start_recording()
        else:
            logger.warning("OBS WebSocket 연결 최종 실패 (host=%s, port=%s)", host, port)
            self._set_state("obs_offline")
