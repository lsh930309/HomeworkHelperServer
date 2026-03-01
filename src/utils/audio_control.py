"""Windows WASAPI 기반 프로세스별 볼륨 제어 유틸리티"""
from __future__ import annotations
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def get_app_volume(pid: int) -> Optional[float]:
    """PID에 해당하는 앱의 현재 볼륨(0.0~1.0) 반환. 없으면 None."""
    try:
        from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume
        sessions = AudioUtilities.GetAllSessions()
        for session in sessions:
            if session.Process and session.Process.pid == pid:
                volume = session._ctl.QueryInterface(ISimpleAudioVolume)
                return volume.GetMasterVolume()
    except (OSError, AttributeError) as e:
        logger.debug(f"get_app_volume PID={pid}: {e}")
    return None


def set_app_volume(pid: int, level: float) -> bool:
    """PID에 해당하는 앱의 볼륨을 설정(0.0~1.0). 성공 여부 반환."""
    level = max(0.0, min(1.0, level))
    try:
        from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume
        sessions = AudioUtilities.GetAllSessions()
        for session in sessions:
            if session.Process and session.Process.pid == pid:
                volume = session._ctl.QueryInterface(ISimpleAudioVolume)
                volume.SetMasterVolume(level, None)
                return True
    except (OSError, AttributeError) as e:
        logger.debug(f"set_app_volume PID={pid} level={level}: {e}")
    return False


def is_muted(pid: int) -> Optional[bool]:
    """PID에 해당하는 앱의 음소거 상태 반환. 없으면 None."""
    try:
        from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume
        sessions = AudioUtilities.GetAllSessions()
        for session in sessions:
            if session.Process and session.Process.pid == pid:
                volume = session._ctl.QueryInterface(ISimpleAudioVolume)
                return bool(volume.GetMute())
    except (OSError, AttributeError) as e:
        logger.debug(f"is_muted PID={pid}: {e}")
    return None


def set_mute(pid: int, mute: bool) -> bool:
    """PID에 해당하는 앱의 음소거 상태 설정."""
    try:
        from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume
        sessions = AudioUtilities.GetAllSessions()
        for session in sessions:
            if session.Process and session.Process.pid == pid:
                volume = session._ctl.QueryInterface(ISimpleAudioVolume)
                volume.SetMute(mute, None)
                return True
    except (OSError, AttributeError) as e:
        logger.debug(f"set_mute PID={pid} mute={mute}: {e}")
    return False
