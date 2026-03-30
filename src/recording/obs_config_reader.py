import os
import json
import configparser
from typing import Optional


def read_obs_config() -> dict:
    """
    Returns dict with keys: port(int), password(str), output_dir(str), exe_path(str)
    각 키는 찾지 못하면 기본값(port=4455, 나머지="")을 사용.
    """
    result = {"port": 4455, "password": "", "output_dir": "", "exe_path": ""}

    appdata = os.environ.get("APPDATA", "")
    obs_dir = os.path.join(appdata, "obs-studio")

    # 1. WebSocket 설정 (포트, 비밀번호)
    ws_cfg_path = os.path.join(obs_dir, "plugin_config", "obs-websocket", "config.json")
    if os.path.isfile(ws_cfg_path):
        try:
            with open(ws_cfg_path, encoding="utf-8") as f:
                ws_cfg = json.load(f)
            result["port"] = int(ws_cfg.get("server_port", 4455))
            result["password"] = str(ws_cfg.get("server_password", ""))
        except Exception:
            pass

    # 2. 현재 프로필 → 출력 경로
    global_ini = os.path.join(obs_dir, "global.ini")
    if os.path.isfile(global_ini):
        try:
            cfg = configparser.RawConfigParser()
            cfg.read(global_ini, encoding="utf-8")
            profile = cfg.get("General", "CurrentProfile", fallback="")
            if profile:
                basic_ini = os.path.join(obs_dir, "basic", "profiles", profile, "basic.ini")
                if os.path.isfile(basic_ini):
                    pcfg = configparser.RawConfigParser()
                    pcfg.read(basic_ini, encoding="utf-8")
                    path = (
                        pcfg.get("SimpleOutput", "FilePath", fallback="")
                        or pcfg.get("AdvOut", "RecFilePath", fallback="")
                    )
                    result["output_dir"] = path
        except Exception:
            pass

    # 3. OBS 실행파일 경로 (레지스트리 → 일반 경로 fallback)
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\OBS Studio")
        install_dir, _ = winreg.QueryValueEx(key, "")
        candidate = os.path.join(install_dir, "bin", "64bit", "obs64.exe")
        if os.path.isfile(candidate):
            result["exe_path"] = candidate
    except Exception:
        pass

    if not result["exe_path"]:
        for candidate in [
            r"C:\Program Files\obs-studio\bin\64bit\obs64.exe",
            r"C:\Program Files (x86)\obs-studio\bin\64bit\obs64.exe",
        ]:
            if os.path.isfile(candidate):
                result["exe_path"] = candidate
                break

    return result
