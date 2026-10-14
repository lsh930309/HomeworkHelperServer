"""Windows runtime observation; no application DB initialization or write paths."""
from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from urllib.request import urlopen

SAFE_SETTINGS = ("run_on_startup", "run_as_admin", "recording_enabled", "obs_exe_path",
                 "obs_launch_hidden", "obs_recording_output_dir", "screenshot_save_dir")


def gui_log(repo: Path, appdata: Path, count: int, contains: str) -> dict:
    sys.path.insert(0, str(repo))
    from src.gui.runtime_logging import redact_sensitive_text
    path = appdata / "HomeworkHelper/homework_helper_data/gui.log"
    if not path.is_file():
        return {"available": False, "reason": "gui_log_missing"}
    with path.open("rb") as stream:
        stream.seek(0, 2)
        start = max(0, stream.tell() - 1024 * 1024)
        stream.seek(start)
        if start:
            stream.readline()  # discard the partial first line before strict UTF-8 decoding
        lines = stream.read().decode("utf-8", errors="strict").splitlines()
    lines = [redact_sensitive_text(line) for line in lines if not contains or contains in line]
    return {"available": True, "path": str(path), "lines": lines[-count:]}


def database_state(path: Path) -> dict:
    if not path.is_file():
        return {"available": False, "reason": "database_missing"}
    try:
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
        try:
            connection.row_factory = sqlite3.Row
            row = connection.execute("SELECT * FROM global_settings LIMIT 1").fetchone()
            settings = {key: row[key] for key in SAFE_SETTINGS if row and key in row.keys()}
            opened = [dict(row) for row in connection.execute(
                "SELECT id,process_id,start_timestamp FROM process_sessions WHERE end_timestamp IS NULL")]
            return {"available": True, "open_sessions": opened, "settings": settings}
        finally:
            connection.close()
    except sqlite3.Error as error:
        return {"available": False, "reason": type(error).__name__}


def process_rows(install: Path) -> list[dict]:
    import psutil
    import pywintypes
    import win32api
    import win32security as security
    rows = []
    for process in psutil.process_iter(["name"]):
        name = (process.info["name"] or "").lower()
        if name not in {"homework_helper.exe", "homework_helper_service.exe", "obs64.exe"}:
            continue
        row = {"pid": process.pid, "name": name}
        try:
            row.update(path=process.exe(), created=process.create_time(), user=process.username())
            handle = win32api.OpenProcess(0x1000, False, process.pid)
            try:
                token = security.OpenProcessToken(handle, security.TOKEN_QUERY)
                try:
                    row.update(sid=security.ConvertSidToStringSid(security.GetTokenInformation(token, security.TokenUser)[0]),
                               session=security.GetTokenInformation(token, security.TokenSessionId),
                               elevated=bool(security.GetTokenInformation(token, security.TokenElevation)))
                finally:
                    token.Close()
            finally:
                handle.Close()
        except (psutil.Error, OSError, pywintypes.error) as error:
            row["error"] = type(error).__name__
        rows.append(row)
    return rows


def obs_outputs(repo: Path, appdata: Path, processes: list[dict]) -> dict:
    if not any(row["name"] == "obs64.exe" for row in processes):
        return {"running": False, "outputs": {}}
    # These modules only define the client/INI readers; do not import src.data.database.
    sys.path.insert(0, str(repo))
    from src.recording.obs_client import OBSClient
    from src.recording.obs_config_reader import read_obs_connection
    client = OBSClient()
    try:
        connection = read_obs_connection()
        if not client.connect(**connection):
            raise OSError("obs_connection_failed")
        outputs = {}
        names = ["GetRecordStatus", "GetStreamStatus", "GetVirtualCamStatus"]
        user = configparser.RawConfigParser()
        with (appdata / "obs-studio/user.ini").open(encoding="utf-8-sig") as stream:
            user.read_file(stream)
        profile = configparser.RawConfigParser()
        with (appdata / "obs-studio/basic/profiles" / user.get("Basic", "ProfileDir") / "basic.ini").open(encoding="utf-8-sig") as stream:
            profile.read_file(stream)
        section = "AdvOut" if profile.get("Output", "Mode", fallback="Simple") == "Advanced" else "SimpleOutput"
        if profile.getboolean(section, "RecRB", fallback=False):
            names.append("GetReplayBufferStatus")
        for name in names:
            reply = client._request(name)
            active = (reply or {}).get("responseData", {}).get("outputActive")
            if type(active) is not bool:
                raise OSError("obs_output_unknown")
            outputs[name] = active
        return {"running": True, "outputs": outputs}
    except (OSError, ValueError, configparser.Error) as error:
        return {"running": True, "error": type(error).__name__, "outputs": {}}
    finally:
        client.disconnect()


def health() -> dict:
    results = {}
    for name in ("ping", "health"):
        try:
            with urlopen(f"http://127.0.0.1:8000/api/gui/{name}", timeout=2) as reply:
                data = json.load(reply)
            results[name] = ({"ok": data.get("ok")} if name == "ping" else
                             {"ok": data.get("ok"), "db_ready": data.get("db_ready"),
                              "mode": data.get("database_access", {}).get("mode")})
        except (OSError, ValueError) as error:
            results[name] = {"error": type(error).__name__}
    return results


def payload_hashes(portable: Path) -> dict:
    import zipfile
    with zipfile.ZipFile(portable) as archive:
        bad = archive.testzip()
        if bad:
            raise ValueError("Portable ZIP CRC failed")
        result = {}
        for filename in ("homework_helper.exe", "homework_helper_service.exe"):
            matches = [name for name in archive.namelist() if name.endswith("/" + filename)]
            if len(matches) != 1:
                raise ValueError("Portable payload is missing or ambiguous")
            result[filename] = hashlib.sha256(archive.read(matches[0])).hexdigest()
        return result


def require_idle(snapshot: dict) -> None:
    if not snapshot["database"].get("available") or snapshot["database"].get("open_sessions"):
        raise ValueError("DB 읽기 실패 또는 사용 중인 게임 세션: 설치 중단")
    h = snapshot["api"]["health"]
    if h.get("ok") is not True or h.get("db_ready") is not True or h.get("mode") != "normal":
        raise ValueError("운영 DB/API가 정상 준비 상태가 아닙니다: 설치 중단")
    obs = snapshot["obs"]
    if obs.get("running") and (obs.get("error") or not obs.get("outputs") or
                               any(active is not False for active in obs["outputs"].values())):
        raise ValueError("OBS 출력 사용 중 또는 상태 미확인: 설치 중단")
    if any(row.get("error") for row in snapshot["processes"]):
        raise ValueError("프로세스 identity 확인 실패: 설치 중단")


def snapshot(repo: Path, appdata: Path, install: Path) -> dict:
    rows = process_rows(install)
    files = {name: hashlib.sha256((install / name).read_bytes()).hexdigest()
             for name in ("homework_helper.exe", "homework_helper_service.exe") if (install / name).is_file()}
    obsdir = appdata / "obs-studio"
    settings_files = {str(path.relative_to(obsdir)): hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in [obsdir / "user.ini", obsdir / "global.ini",
                                  *(obsdir / "basic/profiles").glob("*/basic.ini"),
                                  *(obsdir / "basic/profiles").glob("*/recordEncoder.json")] if path.is_file()}
    return {"processes": rows, "database": database_state(appdata / "HomeworkHelper/homework_helper_data/app_data.db"),
            "api": health(), "obs": obs_outputs(repo, appdata, rows),
            "installed_payload": files, "obs_settings_files": settings_files}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("inspect", "logs", "preflight", "release", "payload", "backup", "build"))
    p.add_argument("--repo", type=Path, required=True)
    p.add_argument("--appdata", type=Path, required=True)
    p.add_argument("--install", type=Path, required=True)
    p.add_argument("--portable", type=Path)
    p.add_argument("--bump", choices=("build", "patch", "minor", "major", "none"), default="build")
    p.add_argument("--log-lines", type=int, default=80)
    p.add_argument("--contains", default="")
    args = p.parse_args(argv)
    os.environ["APPDATA"] = str(args.appdata)
    if args.command == "logs":
        result = gui_log(args.repo, args.appdata, args.log_lines, args.contains)
    elif args.command == "release":
        # Package identity has the same owner as package creation; do not rebuild its naming rules here.
        sys.path.insert(0, str(args.repo))
        from build import load_version_config, make_version_info
        version = make_version_info("windows-host", load_version_config(args.repo / "build.version.json"))
        result = {"release_id": version["string"]}
    elif args.command == "build":
        import subprocess
        log = args.repo / "artifacts/host-operations-build.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("wb") as stream:
            subprocess.run([sys.executable, "build.py", "--no-gui", "--no-prune-archives", "--bump", args.bump],
                           cwd=args.repo, stdout=stream, stderr=subprocess.STDOUT, check=True)
        result = {"build_log": str(log)}
    elif args.command == "payload":
        result = payload_hashes(args.portable)
    elif args.command == "backup":
        # Only this explicitly mutating action uses the existing canonical backup writer.
        sys.path.insert(0, str(args.repo))
        from contextlib import redirect_stdout
        import io
        with redirect_stdout(io.StringIO()):
            from src.data.database import db_path, backup_database, validate_database_integrity
            expected = args.appdata / "HomeworkHelper/homework_helper_data/app_data.db"
            if Path(db_path) != expected:
                raise ValueError("운영 DB 경로 불일치")
            validate_database_integrity(str(expected))
            if not backup_database():
                raise ValueError("정상 DB 백업 실패")
        result = {"backup": str(args.appdata / "HomeworkHelper/backups/app_data.backup.1.db")}
    else:
        result = snapshot(args.repo, args.appdata, args.install)
        if args.command == "preflight":
            require_idle(result)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
