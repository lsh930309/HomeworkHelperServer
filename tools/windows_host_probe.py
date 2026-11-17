"""Windows 관측과 명시적으로 요청한 백업·명조 오프라인 복구를 수행한다."""
from __future__ import annotations

import argparse
import configparser
from datetime import datetime, timezone
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
            fields = ("resource_tracking_enabled", "resource_key", "resource_current", "resource_max",
                      "resource_reserve_current", "resource_reserve_max", "resource_status", "resource_updated_at")
            columns = {row[1] for row in connection.execute("PRAGMA table_info(managed_processes)")}
            supported = {"resource_provider", *fields} <= columns
            resources = []
            if supported:
                for resource in connection.execute(
                        "SELECT " + ",".join(fields) + " FROM managed_processes WHERE resource_provider='wuwa'"):
                    resources.append({"tracking_enabled": bool(resource["resource_tracking_enabled"]),
                                      "fixed_resource_key": resource["resource_key"] == "waveplate",
                                      **{key: resource[key] for key in fields[2:]}})
            return {"available": True, "open_sessions": opened, "settings": settings,
                    "wuwa_resources": {"supported": supported, "rows": resources}}
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


def repair_wuwa_link(repo: Path, appdata: Path, install: Path) -> dict:
    """수정본 설치 후 앱이 없는 상태에서 기존 계정 사실만 옮긴다."""
    import io
    from contextlib import closing, redirect_stdout

    processes = process_rows(install)
    if any(row.get("error") or row.get("name") == "homework_helper.exe" for row in processes):
        raise ValueError("호스트 GUI/API 종료를 확인할 수 없어 오프라인 복구를 중단합니다.")
    expected = appdata / "HomeworkHelper/homework_helper_data/app_data.db"
    backup = appdata / "HomeworkHelper/backups/app_data.backup.1.db"
    if not expected.is_file() or not backup.is_file():
        raise ValueError("기존 운영 DB와 설치 전 정상 백업이 모두 필요합니다.")

    def read_rows(path):
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)) as connection:
            if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise ValueError("DB 무결성 검사가 실패하여 오프라인 복구를 중단합니다.")
            connection.row_factory = sqlite3.Row
            return {table: [dict(row) for row in connection.execute(f'SELECT * FROM "{table}" ORDER BY id')]
                    for table in ("managed_processes", "process_sessions", "global_settings")}

    read_rows(backup)
    backup_original = backup.read_bytes()
    before = read_rows(expected)
    sys.path.insert(0, str(repo))
    try:
        with redirect_stdout(io.StringIO()):
            from sqlalchemy import create_engine
            from sqlalchemy.orm import Session
            from src.data import crud, database
            from src.utils.wuwa_config import WuwaConfig
            if Path(database.db_path).resolve() != expected.resolve():
                raise ValueError("운영 DB 경로 불일치")
            engine = create_engine("sqlite:///" + expected.as_posix(), connect_args={"timeout": 5})
            try:
                with Session(engine) as session:
                    migration = crud.configure_wuwa_link(session, migrate=True, config=WuwaConfig(expected.parent.parent))
            finally:
                engine.dispose()
    except Exception:
        raise ValueError("명조 오프라인 복구 writer가 실패했습니다. 앱을 시작하지 않습니다.") from None
    after = read_rows(expected)
    allowed = {"resource_key", "resource_percent", "resource_updated_at", "resource_status", "resource_label",
               "resource_current", "resource_max", "resource_reserve_current", "resource_reserve_max"}
    before_processes = {row["id"]: row for row in before["managed_processes"]}
    after_processes = {row["id"]: row for row in after["managed_processes"]}
    ids_preserved = before_processes.keys() == after_processes.keys()
    other_data_preserved = ids_preserved and all(
        row == after_processes[key] if row.get("resource_provider") != "wuwa" else
        {k: v for k, v in row.items() if k not in allowed} ==
        {k: v for k, v in after_processes[key].items() if k not in allowed}
        for key, row in before_processes.items()
    )
    preserved = {"game_ids": ids_preserved, "sessions": before["process_sessions"] == after["process_sessions"],
                 "settings": before["global_settings"] == after["global_settings"],
                 "unrelated_process_data": other_data_preserved, "backup": backup.read_bytes() == backup_original}
    if not all(preserved.values()):
        raise ValueError("명조 오프라인 복구 후 기존 데이터 보존 검사가 실패했습니다. 앱을 시작하지 않습니다.")
    if any(row.get("error") or row.get("name") == "homework_helper.exe" for row in process_rows(install)):
        raise ValueError("오프라인 복구 중 호스트 앱 실행이 감지되었습니다. 자동 시작하지 않습니다.")
    if migration.get("connected") is not True or migration.get("selection_required") is not False:
        raise ValueError("명조 연결 계정을 확정하지 못했습니다. 앱을 시작하지 않습니다.")
    migration_summary = {key: migration[key] for key in (
        "connected", "migrated", "selection_required", "normalized_count", "cleared_count")}
    return {"ok": True, "migration": migration_summary, "preserved": preserved,
            "completed_at_utc": datetime.now(timezone.utc).isoformat(), "gui_api_absent": True,
            "process_count": len(after_processes), "session_count": len(after["process_sessions"])}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("inspect", "logs", "preflight", "release", "payload", "backup", "build", "prepare-runtime", "repair-wuwa-link"))
    p.add_argument("--repo", type=Path, required=True)
    p.add_argument("--appdata", type=Path, required=True)
    p.add_argument("--install", type=Path, required=True)
    p.add_argument("--portable", type=Path)
    p.add_argument("--expected-commit")
    p.add_argument("--expected-version")
    p.add_argument("--log-lines", type=int, default=80)
    p.add_argument("--contains", default="")
    args = p.parse_args(argv)
    os.environ["APPDATA"] = str(args.appdata)
    if args.command == "logs":
        result = gui_log(args.repo, args.appdata, args.log_lines, args.contains)
    elif args.command == "release":
        # Package identity has the same owner as package creation; do not rebuild its naming rules here.
        sys.path.insert(0, str(args.repo))
        from build import load_windows_version_info, windows_package_paths
        version = load_windows_version_info(args.repo)
        if (args.expected_commit is not None or args.expected_version is not None) and (
                version["git_hash"], version["version"]) != (args.expected_commit, args.expected_version):
            raise ValueError("Windows 패키지 선택의 요청 커밋 또는 버전과 다릅니다.")
        setup, portable = windows_package_paths(version, args.repo / "release")
        result = {"release_id": version["string"], "setup": str(setup), "portable": str(portable)}
    elif args.command == "prepare-runtime":
        import subprocess
        log = args.repo / "artifacts/media-qa-requirements.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("wb") as stream:
            subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
                           cwd=args.repo, stdout=stream, stderr=subprocess.STDOUT, check=True)
        result = {"requirements_log": str(log)}
    elif args.command == "build":
        import subprocess
        log = args.repo / "artifacts/host-operations-build.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("wb") as stream:
            subprocess.run([sys.executable, "build.py", "--no-prune-archives"],
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
    elif args.command == "repair-wuwa-link":
        result = repair_wuwa_link(args.repo, args.appdata, args.install)
    else:
        result = snapshot(args.repo, args.appdata, args.install)
        if args.command == "preflight":
            require_idle(result)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
