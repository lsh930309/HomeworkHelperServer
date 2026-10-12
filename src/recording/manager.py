import threading
import time
import logging
from typing import Callable, Literal, Optional

from src.recording.obs_client import OBSClient
from src.recording.obs_config_reader import read_obs_connection, read_obs_output_directory, find_obs_executable

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
        self._pending_control = None
        self._info_refresh_active = False
        self._startup_requested = False
        self._info = {"exe_path": "", "output_dir": ""}
        self._on_info_changed: Optional[Callable[[], None]] = None
        self._client.set_on_record_state_changed(self._on_record_state_changed_from_obs)
        self._client.set_on_connection_closed(self._on_connection_closed)

    # ---------- settings ----------

    def _set_settings(self, settings) -> None:
        values = {
            "enabled": getattr(settings, "recording_enabled", False),
        }
        with self._lock:
            self._settings = values

    def prepare_for_startup(self, settings) -> None:
        """One app initialization trigger, independent of recording settings."""
        if self._startup_requested:
            return
        self._startup_requested = True
        self._set_settings(settings)
        self._try_connect_async(launch_requested=True, connect_requested=None)

    def apply_settings(self, settings) -> None:
        """Refresh settings without launching OBS."""
        with self._lock:
            previous = dict(self._settings)
        self._set_settings(settings)
        if previous != self._settings or (self._settings["enabled"] and not self._client.is_connected()):
            self._try_connect_async(connect_requested=self._settings["enabled"])

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
        # The existing worker reads the actual directory before issuing StartRecord.
        self._try_connect_async(then_record=True, launch_requested=not self._client.is_connected())

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
        with self._lock:
            if not self._settings.get("enabled"):
                return
        self._try_connect_async(then_record=False, launch_requested=True)

    def refresh_info(self) -> None:
        """Read-only settings view: no process launch, connection or recording request."""
        self._try_connect_async(read_only=True)

    def set_on_info_changed(self, fn: Callable[[], None]) -> None:
        self._on_info_changed = fn

    def get_obs_info(self) -> dict:
        with self._lock:
            info = dict(self._info)
            info["state"] = self._state
            info["enabled"] = self._settings.get("enabled", False)
        # A completed file lookup owns its own error. An old request error on a
        # healthy connection must not turn a successful lookup back into failure.
        info["error"] = info.get("error") or self._launch_error
        return info

    def get_output_directory(self) -> str:
        with self._lock:
            return self._info["output_dir"]

    def _publish_info(self, *, exe_path: str, output_dir: str, error: str = "") -> None:
        with self._lock:
            if self._connect_thread is not threading.current_thread():
                return
            info = {"exe_path": exe_path, "output_dir": output_dir, "error": error}
            if self._info == info:
                return
            self._info = info
        callback = self._on_info_changed
        if callback:
            callback()

    def get_last_error(self) -> str:
        return self._launch_error or self._client.get_last_error()

    def shutdown(self) -> None:
        with self._lock:
            self._connect_thread = None
            self._pending_control = None
            self._settings = {}
        self._on_state_changed = None
        self._on_info_changed = None
        self._client.set_on_connection_closed(None)
        self._client.set_on_record_state_changed(None)
        self._client.disconnect()
        self._set_state("obs_offline")

    # ---------- internal ----------

    def _get_state(self) -> RecordingState:
        with self._lock:
            return self._state

    def _set_state(self, state: RecordingState, *, elapsed_seconds: Optional[float] = None,
                   from_obs: bool = False) -> None:
        changed = False
        with self._lock:
            if from_obs and (not self._settings or not self._settings["enabled"] or
                             not self._client.is_connected()):
                return
            if self._state != state:
                self._state = state
                changed = True
                if state == "recording":
                    self._recording_start_time = time.monotonic()
                elif state != "recording":
                    self._recording_start_time = None
            if state == "recording" and elapsed_seconds is not None:
                self._recording_start_time = time.monotonic() - max(0, elapsed_seconds)
        callback = self._on_state_changed
        if changed and callback:
            callback(state)

    def _on_record_state_changed_from_obs(self, active: bool, *, elapsed_seconds=None) -> None:
        self._set_state("recording" if active else "idle", elapsed_seconds=elapsed_seconds, from_obs=True)

    def _on_connection_closed(self) -> None:
        self._launch_error = self._client.get_last_error()
        self._set_state("obs_offline")

    def _try_connect_async(self, then_record: bool = False, launch_requested: bool = False,
                           connect_requested: Optional[bool] = True, read_only: bool = False) -> None:
        with self._lock:
            if not self._settings:
                return
            active = self._connect_thread
            if active is not None:
                if self._info_refresh_active and not read_only:
                    self._pending_control = (then_record, launch_requested, connect_requested)
                return
            thread = threading.Thread(
                target=self._connect_worker,
                args=(then_record, launch_requested, connect_requested, dict(self._settings), read_only),
                daemon=True,
            )
            self._connect_thread = thread
            self._info_refresh_active = read_only
        if not read_only:
            self._set_state("connecting")
        thread.start()

    def _work_settings(self) -> Optional[dict]:
        """The current worker consumes the latest desired settings; shutdown revokes ownership."""
        with self._lock:
            return dict(self._settings) if self._connect_thread is threading.current_thread() else None

    def _read_info(self) -> None:
        """Observe file information independently of OBS process/control readiness."""
        executable, directory, errors = "", "", []
        try:
            executable = find_obs_executable()
        except (OSError, ValueError) as error:
            errors.append(str(error))
        try:
            directory = (self._client.get_record_directory() if self._client.is_connected()
                         else read_obs_output_directory())
            if directory is None:
                raise OSError(self._client.get_last_error())
        except (OSError, ValueError) as error:
            directory = ""
            errors.append(str(error))
        if errors:
            logger.warning("OBS 정보 조회 실패: %s", "; ".join(errors))
        self._publish_info(exe_path=executable, output_dir=directory, error="; ".join(errors))

    def _connect_worker(self, then_record: bool, launch_requested: bool,
                        connect_requested: Optional[bool], s: dict, read_only: bool) -> None:
        try:
            if not read_only:
                self._launch_error = ""
            if read_only or not self._client.is_connected():
                self._read_info()
                if read_only:
                    return
                if self._work_settings() is None:
                    return
            if launch_requested:
                from src.host_service.client import HostPrivilegeClient, PrivilegeServiceError
                try:
                    result = HostPrivilegeClient().launch_obs()
                    latest = self._work_settings()
                    if latest is None:
                        return
                    needs_connection = latest["enabled"] if connect_requested is None else connect_requested
                    if needs_connection and not result.get("already_running"):
                        time.sleep(5)
                except PrivilegeServiceError as error:
                    if self._work_settings() is None:
                        return
                    self._launch_error = str(error)
                    logger.warning("OBS 관리자 실행 실패: %s", error)
                    self._set_state("obs_offline")
                    return

            if connect_requested is None:
                s = self._work_settings()
                if s is None:
                    return
                connect_requested = s["enabled"]
            connect_requested = bool(connect_requested and s["enabled"])
            while True:
                latest = self._work_settings()
                if latest is None:
                    self._client.disconnect()
                    return
                if latest != s:
                    s, connect_requested, then_record = latest, latest["enabled"], False
                if not connect_requested:
                    self._client.disconnect()
                    self._set_state("obs_offline")
                else:
                    self._set_state("connecting")
                    logger.info("OBS WebSocket 자동 연결 준비")
                    connection = read_obs_connection()
                    ok = False
                    for attempt in range(2):
                        if self._work_settings() != s:
                            break
                        ok = (self._client.connection_matches(**connection) or self._client.connect(**connection))
                        if ok or self._work_settings() != s:
                            break
                        if attempt == 0:
                            logger.warning("OBS WebSocket 1차 연결 실패, 3초 후 재시도...")
                            time.sleep(3)
                    if self._work_settings() != s:
                        continue
                    # Files are observed before a record request, but their lookup
                    # outcome cannot stop an otherwise healthy control connection.
                    if ok:
                        self._read_info()
                    if self._work_settings() != s:
                        continue
                    # The WebSocket thread applies this response before subsequent record events.
                    if ok:
                        status = self._client.get_record_status()
                        ok = status is not None
                    if self._work_settings() != s:
                        continue
                    if ok:
                        logger.info("OBS WebSocket 연결과 녹화 상태 확인 성공")
                        if then_record and not status["outputActive"]:
                            if self._client.start_record() is False:
                                raise OSError(self._client.get_last_error())
                    else:
                        logger.warning("OBS 연결 또는 녹화 상태 확인 실패")
                        self._launch_error = self._client.get_last_error()
                        self._client.disconnect()
                        self._set_state("obs_offline")
                # A settings callback delivered while publishing the result is consumed by this worker.
                with self._lock:
                    if self._connect_thread is not threading.current_thread():
                        return
                    if self._settings == s:
                        return
        except (OSError, ValueError) as error:
            if self._work_settings() is not None:
                logger.warning("OBS 연동 준비 실패: %s", error)
                if not read_only:
                    self._launch_error = str(error)
                    self._client.disconnect()
                    self._set_state("obs_offline")
                if self._on_info_changed:
                    self._on_info_changed()
        finally:
            with self._lock:
                pending = None
                if self._connect_thread is threading.current_thread():
                    self._connect_thread = None
                    pending, self._pending_control = self._pending_control, None
            if pending is not None:
                self._try_connect_async(*pending)
