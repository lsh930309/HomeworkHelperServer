import subprocess
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
        self._connect_thread: Optional[threading.Thread] = None
        self._client.set_on_record_state_changed(self._on_record_state_changed_from_obs)

    # ---------- settings ----------

    def apply_settings(self, settings) -> None:
        """GlobalSettings 객체를 받아 설정 적용 및 연결 시도."""
        self._settings = {
            "enabled": getattr(settings, "recording_enabled", False),
            "host": getattr(settings, "obs_host", "localhost"),
            "port": getattr(settings, "obs_port", 4455),
            "password": getattr(settings, "obs_password", ""),
            "exe_path": getattr(settings, "obs_exe_path", ""),
            "auto_launch": getattr(settings, "obs_auto_launch", False),
            "launch_hidden": getattr(settings, "obs_launch_hidden", True),
        }
        if self._settings["enabled"]:
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
            # auto_launch 시도 후 녹화 시작
            self._try_connect_async(then_record=True)

    def start_recording(self) -> None:
        if not self._client.is_connected():
            logger.warning("OBS not connected, cannot start recording")
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

    def shutdown(self) -> None:
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
        if changed and self._on_state_changed:
            self._on_state_changed(state)

    def _on_record_state_changed_from_obs(self, active: bool) -> None:
        self._set_state("recording" if active else "idle")

    def _try_connect_async(self, then_record: bool = False) -> None:
        if self._connect_thread and self._connect_thread.is_alive():
            return
        self._set_state("connecting")
        self._connect_thread = threading.Thread(
            target=self._connect_worker,
            args=(then_record,),
            daemon=True,
        )
        self._connect_thread.start()

    def _connect_worker(self, then_record: bool) -> None:
        s = self._settings
        # auto_launch: OBS 프로세스 실행
        if s.get("auto_launch") and s.get("exe_path"):
            self._launch_obs(s["exe_path"], s.get("launch_hidden", True))
            time.sleep(3)  # OBS 기동 대기

        ok = self._client.connect(
            host=s.get("host", "localhost"),
            port=s.get("port", 4455),
            password=s.get("password", ""),
        )
        if ok:
            self._set_state("idle")
            if then_record:
                self.start_recording()
        else:
            self._set_state("obs_offline")

    @staticmethod
    def _launch_obs(exe_path: str, hidden: bool) -> None:
        try:
            import os
            import psutil
            exe_name = os.path.basename(exe_path).lower()
            if any(p.name().lower() == exe_name for p in psutil.process_iter(["name"])):
                logger.debug("OBS already running, skipping launch")
                return
            args = [exe_path]
            if hidden:
                args.append("--startminimized")
            # OBS는 자신의 설치 디렉토리를 cwd로 실행해야 locale 파일을 찾을 수 있음
            obs_dir = os.path.dirname(exe_path)
            subprocess.Popen(args, cwd=obs_dir)
        except Exception as e:
            logger.warning("Failed to launch OBS: %s", e)
