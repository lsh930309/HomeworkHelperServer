"""Windows WASAPI 오디오 세션 접근. COM은 호출한 worker 안에서만 소비한다."""
from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AudioSession:
    endpoint_id: str
    instance_id: str
    pid: int
    _volume: Any = field(repr=False, compare=False)

    @property
    def key(self) -> tuple[str, str]:
        return self.endpoint_id, self.instance_id

    def get_volume(self) -> float:
        return float(self._volume.GetMasterVolume())

    def get_mute(self) -> bool:
        return bool(self._volume.GetMute())

    def set_volume(self, level: float) -> None:
        self._volume.SetMasterVolume(max(0.0, min(1.0, level)), None)

    def set_mute(self, muted: bool) -> None:
        self._volume.SetMute(bool(muted), None)


def enumerate_sessions() -> tuple[AudioSession, ...]:
    """활성 render 장치 전체의 세션을 열거한다. 실패를 빈 결과로 숨기지 않는다."""
    import comtypes
    from pycaw.pycaw import AudioUtilities, IAudioSessionControl2, IAudioSessionManager2, ISimpleAudioVolume

    devices = AudioUtilities.GetDeviceEnumerator().EnumAudioEndpoints(0, 1)  # eRender, DEVICE_STATE_ACTIVE
    sessions = []
    for device_index in range(devices.GetCount()):
        device = devices.Item(device_index)
        endpoint_id = str(device.GetId())
        manager = device.Activate(IAudioSessionManager2._iid_, comtypes.CLSCTX_ALL, None)
        enumerator = manager.QueryInterface(IAudioSessionManager2).GetSessionEnumerator()
        for session_index in range(enumerator.GetCount()):
            control = enumerator.GetSession(session_index).QueryInterface(IAudioSessionControl2)
            pid = int(control.GetProcessId())
            if not pid or int(control.GetState()) == 2:  # System Sounds / expired
                continue
            sessions.append(AudioSession(
                endpoint_id, str(control.GetSessionInstanceIdentifier()), pid,
                control.QueryInterface(ISimpleAudioVolume),
            ))
    return tuple(sessions)


def verify_identity(target) -> bool:
    """PID 재사용·경로 변경·다른 사용자 세션에 이전 정책을 적용하지 않는다."""
    import psutil
    from src.core.process_monitor import _belongs_to_current_user_session, _normalize_process_path

    try:
        process = psutil.Process(target.pid)
        return (process.is_running()
                and abs(process.create_time() - target.create_time) <= 0.001
                and _normalize_process_path(process.exe()) == _normalize_process_path(target.path)
                and _belongs_to_current_user_session(process))
    except psutil.NoSuchProcess:
        return False


def _pid_volumes(pid: int):
    """기존 공개 함수의 pycaw 진입점을 유지하며 일치 세션을 모두 다룬다."""
    from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume
    for session in AudioUtilities.GetAllSessions():
        if session.Process and session.Process.pid == pid:
            yield session._ctl.QueryInterface(ISimpleAudioVolume)


def get_app_volume(pid: int) -> Optional[float]:
    """기존 기본 출력 장치에서 PID의 가장 큰 세션 볼륨. 없거나 실패하면 None."""
    try:
        values = [float(volume.GetMasterVolume()) for volume in _pid_volumes(pid)]
        return max(values) if values else None
    except Exception:
        logger.warning("게임 볼륨 조회 실패: PID=%s", pid, exc_info=True)
        return None


def set_app_volume(pid: int, level: float) -> bool:
    """기존 기본 출력 장치에서 PID의 모든 세션 볼륨을 설정한다."""
    try:
        volumes = tuple(_pid_volumes(pid))
    except Exception:
        logger.warning("게임 볼륨 설정 실패: PID=%s", pid, exc_info=True)
        return False
    succeeded = bool(volumes)
    for volume in volumes:
        try:
            volume.SetMasterVolume(max(0.0, min(1.0, level)), None)
        except Exception:
            succeeded = False
            logger.warning("게임 세션 볼륨 설정 실패: PID=%s", pid, exc_info=True)
    return succeeded


def is_muted(pid: int) -> Optional[bool]:
    """기존 기본 출력 장치에서 PID의 모든 세션이 muted인지 읽는다."""
    try:
        values = [bool(volume.GetMute()) for volume in _pid_volumes(pid)]
        return all(values) if values else None
    except Exception:
        logger.warning("게임 음소거 조회 실패: PID=%s", pid, exc_info=True)
        return None


def set_mute(pid: int, mute: bool) -> bool:
    """기존 기본 출력 장치에서 PID의 모든 세션 음소거를 설정한다."""
    try:
        volumes = tuple(_pid_volumes(pid))
    except Exception:
        logger.warning("게임 음소거 설정 실패: PID=%s", pid, exc_info=True)
        return False
    succeeded = bool(volumes)
    for volume in volumes:
        try:
            volume.SetMute(bool(mute), None)
        except Exception:
            succeeded = False
            logger.warning("게임 세션 음소거 설정 실패: PID=%s", pid, exc_info=True)
    return succeeded
