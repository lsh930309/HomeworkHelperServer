"""명시 설치 복구는 앱 없이 실행하며 계정 사실 외 운영 데이터를 보존한다."""
from contextlib import closing
import json
import sqlite3

import pytest

from tools import host_operations as ops
from tools import windows_host_probe as probe


def test_repair_option_is_install_only_and_forwarded(monkeypatch, tmp_path):
    args = ops.parser().parse_args(["install", "--host", "fixture.invalid", "--repair-wuwa-link"])
    assert " -RepairWuwaLink" in ops.remote_script(args)
    monkeypatch.setattr(ops, "run_remote_powershell", lambda *_args, **_kwargs: pytest.fail("원격 접근 금지"))
    for arguments in (["inspect"], ["install", "--archived-release", "dev.2"]):
        with pytest.raises(SystemExit):
            ops.main([*arguments, "--host", "fixture.invalid", "--repair-wuwa-link", "--report-root", str(tmp_path)])
    assert not list(tmp_path.iterdir())


@pytest.fixture
def offline_data(tmp_path, monkeypatch):
    appdata = tmp_path / "roaming"
    base = appdata / "HomeworkHelper"
    path = base / "homework_helper_data/app_data.db"
    path.parent.mkdir(parents=True)
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("HH_TEST_APPDATA_DIR", str(base))
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript("""
            CREATE TABLE managed_processes(id TEXT PRIMARY KEY,resource_provider TEXT,resource_key TEXT,name TEXT,resource_current INTEGER);
            INSERT INTO managed_processes VALUES('wuwa','wuwa','waveplate@Asia@799900001','명조',240);
            INSERT INTO managed_processes VALUES('other','nikke_blablalink','nikke_outpost_storage','다른 게임',50);
            CREATE TABLE process_sessions(id INTEGER PRIMARY KEY,process_id TEXT,end_timestamp REAL);
            INSERT INTO process_sessions VALUES(1,'wuwa',100);
            CREATE TABLE global_settings(id INTEGER PRIMARY KEY,bgm_enabled INTEGER,private_value TEXT);
            INSERT INTO global_settings VALUES(1,0,'fixture-private');
        """)
        connection.commit()
        backup = base / "backups/app_data.backup.1.db"
        backup.parent.mkdir()
        with closing(sqlite3.connect(backup)) as destination:
            connection.backup(destination)
    # 파일·자격 증명 접근 경계는 임시 APPDATA로 확정한 뒤에만 제품 writer 모듈을 import한다.
    from src.data import crud, database
    monkeypatch.setattr(database, "db_path", str(path))
    monkeypatch.setattr(probe, "process_rows", lambda *_args: [])
    calls = []

    def migrate(session, *, migrate, config):
        assert migrate is True and config.config_dir == base
        calls.append("repair")
        session.connection().exec_driver_sql("UPDATE managed_processes SET resource_key='waveplate' WHERE id='wuwa'")
        session.commit()
        return {"connected": True, "migrated": True, "selection_required": False,
                "normalized_count": 1, "cleared_count": 0, "private_extra": "fixture-private"}

    monkeypatch.setattr(crud, "configure_wuwa_link", migrate)
    return tmp_path, appdata, path, backup, calls


def test_offline_repair_preserves_records_and_omits_account_values(offline_data):
    repo, appdata, path, backup, calls = offline_data
    original_backup = backup.read_bytes()
    result = probe.repair_wuwa_link(repo, appdata, repo / "installed")
    assert result["ok"] and all(result["preserved"].values())
    assert result["process_count"] == 2 and result["session_count"] == 1 and calls == ["repair"]
    assert "799900001" not in json.dumps(result) and "fixture-private" not in json.dumps(result)
    assert backup.read_bytes() == original_backup
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("SELECT resource_key,resource_current FROM managed_processes WHERE id='wuwa'").fetchone() == ("waveplate", 240)


@pytest.mark.parametrize("blocked", ["running", "unknown", "missing-backup"])
def test_offline_repair_refuses_before_writer_without_offline_backup(offline_data, monkeypatch, blocked):
    repo, appdata, path, backup, calls = offline_data
    if blocked == "missing-backup":
        backup.unlink()
    else:
        monkeypatch.setattr(probe, "process_rows", lambda *_args: [{"name": "homework_helper.exe"}] if blocked == "running" else [{"error": "AccessDenied"}])
    before = path.read_bytes()
    with pytest.raises(ValueError):
        probe.repair_wuwa_link(repo, appdata, repo / "installed")
    assert calls == [] and path.read_bytes() == before


def test_offline_repair_stops_when_unrelated_data_changes(offline_data, monkeypatch):
    repo, appdata, _path, _backup, _calls = offline_data
    from src.data import crud
    original = crud.configure_wuwa_link

    def broken_writer(session, **kwargs):
        result = original(session, **kwargs)
        session.connection().exec_driver_sql("UPDATE global_settings SET bgm_enabled=1")
        session.commit()
        return result

    monkeypatch.setattr(crud, "configure_wuwa_link", broken_writer)
    with pytest.raises(ValueError, match="보존 검사"):
        probe.repair_wuwa_link(repo, appdata, repo / "installed")


def test_unresolved_account_is_not_reported_as_completed_repair(offline_data, monkeypatch):
    repo, appdata, _path, _backup, _calls = offline_data
    from src.data import crud
    monkeypatch.setattr(crud, "configure_wuwa_link", lambda *_args, **_kwargs: {
        "connected": False, "migrated": True, "selection_required": True, "normalized_count": 0, "cleared_count": 0})
    with pytest.raises(ValueError, match="계정을 확정하지 못했습니다"):
        probe.repair_wuwa_link(repo, appdata, repo / "installed")


def test_offline_writer_error_does_not_expose_account_or_credentials(offline_data, monkeypatch):
    repo, appdata, _path, _backup, _calls = offline_data
    from src.data import crud
    def fail(*_args, **_kwargs):
        raise ValueError("799900001 fixture-private-token")
    monkeypatch.setattr(crud, "configure_wuwa_link", fail)
    with pytest.raises(ValueError, match="writer가 실패") as error:
        probe.repair_wuwa_link(repo, appdata, repo / "installed")
    assert "799900001" not in str(error.value) and "fixture-private" not in str(error.value)
    assert error.value.__suppress_context__ is True


def test_install_repairs_after_payload_verification_and_before_start():
    source = (ops.ROOT / "tools/windows_host_operations.ps1").read_text(encoding="utf-8")
    install = source[source.index("    'install' {"):]
    assert install.index("$Installer.ExitCode") < install.index("$Repair = Invoke-Probe 'repair-wuwa-link'") < install.index("Start-UserApp $Status")
    assert install.index("설치 payload와 패키지 불일치") < install.index("$Repair = Invoke-Probe 'repair-wuwa-link'")


def test_inspect_reports_only_wuwa_resource_values_and_schema_support(tmp_path):
    path = tmp_path / "observe.db"
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript("""
            CREATE TABLE global_settings(id INTEGER PRIMARY KEY,run_on_startup INTEGER);
            INSERT INTO global_settings VALUES(1,1);
            CREATE TABLE process_sessions(id INTEGER,process_id TEXT,start_timestamp REAL,end_timestamp REAL);
        """)
        connection.commit()
    assert probe.database_state(path)["wuwa_resources"] == {"supported": False, "rows": []}
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript("""
            CREATE TABLE managed_processes(id TEXT,name TEXT,resource_provider TEXT,resource_tracking_enabled INTEGER,
                resource_key TEXT,resource_current INTEGER,resource_max INTEGER,resource_reserve_current INTEGER,
                resource_reserve_max INTEGER,resource_status TEXT,resource_updated_at REAL);
            INSERT INTO managed_processes VALUES('private-game-id','private-name','wuwa',1,'waveplate@Asia@799900001',240,240,120,480,'ok',100);
        """)
        connection.commit()
    original = path.read_bytes()
    result = probe.database_state(path)["wuwa_resources"]
    assert result == {"supported": True, "rows": [{"tracking_enabled": True, "fixed_resource_key": False,
        "resource_current": 240, "resource_max": 240, "resource_reserve_current": 120,
        "resource_reserve_max": 480, "resource_status": "ok", "resource_updated_at": 100.0}]}
    assert "private" not in json.dumps(result) and "799900001" not in json.dumps(result)
    assert path.read_bytes() == original
