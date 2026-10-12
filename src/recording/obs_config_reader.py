"""Read OBS-owned configuration and its installed executable; never write it."""
import configparser
import json
import os
from pathlib import Path


def _obs_directory() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise OSError("OBS 설정 위치를 확인하지 못했습니다.")
    return Path(appdata) / "obs-studio"


def read_obs_connection() -> dict:
    """The local OBS server owns port/authentication; unreadable values fail explicitly."""
    path = _obs_directory() / "plugin_config" / "obs-websocket" / "config.json"
    try:
        with path.open(encoding="utf-8-sig") as stream:
            settings = json.load(stream)
        if settings["server_enabled"] is not True:
            raise ValueError("OBS에서 WebSocket 서버를 켜 주세요.")
        port = settings["server_port"]
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("OBS WebSocket 포트가 올바르지 않습니다.")
        authenticated = settings["auth_required"]
        if type(authenticated) is not bool:
            raise ValueError("OBS WebSocket 인증 설정이 올바르지 않습니다.")
        password = settings["server_password"] if authenticated else ""
        if not isinstance(password, str) or (authenticated and not password):
            raise ValueError("OBS WebSocket 비밀번호를 확인해 주세요.")
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise OSError("OBS WebSocket 설정을 읽지 못했습니다. OBS의 WebSocket 서버 설정을 확인해 주세요.") from error
    return {"host": "localhost", "port": port, "password": password}


def read_obs_output_directory() -> str:
    """Offline information only. A connected OBS's GetRecordDirectory is authoritative."""
    directory = _obs_directory()
    try:
        user = configparser.RawConfigParser()
        with (directory / "user.ini").open(encoding="utf-8-sig") as stream:
            user.read_file(stream)
        profile = user.get("Basic", "ProfileDir")
        settings = configparser.RawConfigParser()
        with (directory / "basic" / "profiles" / profile / "basic.ini").open(encoding="utf-8-sig") as stream:
            settings.read_file(stream)
        if settings.get("Output", "Mode", fallback="Simple") == "Advanced":
            path = settings.get("AdvOut", "RecFilePath")
        else:
            path = settings.get("SimpleOutput", "FilePath")
        if not path.strip():
            raise OSError("OBS 녹화 저장 폴더가 비어 있습니다.")
        return path
    except (OSError, configparser.Error) as error:
        raise OSError("OBS의 현재 녹화 저장 폴더를 읽지 못했습니다. OBS에서 확인해 주세요.") from error


def find_obs_executable() -> str:
    """Shared GUI/service discovery. The service calls this as the designated user."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\OBS Studio") as key:
            install_directory, _ = winreg.QueryValueEx(key, "")
        candidate = Path(install_directory) / "bin" / "64bit" / "obs64.exe"
        if candidate.is_absolute() and candidate.is_file():
            return str(candidate)
    except (OSError, ImportError):
        pass
    for directory in (r"C:\Program Files\obs-studio", r"C:\Program Files (x86)\obs-studio"):
        candidate = Path(directory) / "bin" / "64bit" / "obs64.exe"
        if candidate.is_absolute() and candidate.is_file():
            return str(candidate)
    raise FileNotFoundError("OBS 설치를 찾지 못했습니다. OBS가 설치돼 있는지 확인해 주세요.")
