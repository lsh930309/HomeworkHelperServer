from __future__ import annotations

import concurrent.futures
import hashlib
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from src.data.database_coordination import (
    DatabaseAccessUnavailable,
    DatabaseDrainTimeout,
    DatabaseFaultStatePersistenceError,
    DatabaseMaintenanceCoordinator,
    database_access_exception_handler,
)


def _write_marker_database(path, marker: str) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE marker (value TEXT NOT NULL)")
        connection.execute("INSERT INTO marker (value) VALUES (?)", (marker,))
        connection.commit()


def _read_marker_database(path) -> str:
    with closing(sqlite3.connect(path)) as connection:
        return str(connection.execute("SELECT value FROM marker").fetchone()[0])


def _sha256(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _restore_client(monkeypatch, tmp_path):
    import src.api.beholder_routes as routes

    data_dir = tmp_path / "homework_helper_data"
    backup_dir = tmp_path / "backups"
    data_dir.mkdir()
    backup_dir.mkdir()
    current_db = data_dir / "app_data.db"
    backup_db = backup_dir / "app_data.backup.1.db"
    _write_marker_database(current_db, "old")
    _write_marker_database(backup_db, "new")
    coordinator = DatabaseMaintenanceCoordinator(
        fault_state_path=data_dir / "database_fault_state.json"
    )

    monkeypatch.setattr(routes, "base_dir", str(tmp_path))
    monkeypatch.setattr(routes, "data_dir", str(data_dir))
    monkeypatch.setattr(routes, "db_path", str(current_db))
    monkeypatch.setattr(routes, "database_coordinator", coordinator)
    monkeypatch.setattr(routes.engine, "dispose", lambda: None)
    monkeypatch.setattr(
        routes,
        "_strict_prepare_live_database",
        lambda: routes._require_valid_sqlite_backup(current_db),
    )

    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app), routes, coordinator, current_db


def test_request_lease_can_be_released_on_another_thread_and_is_idempotent():
    coordinator = DatabaseMaintenanceCoordinator()
    lease = coordinator.acquire_request("cross-thread")

    thread = threading.Thread(target=lambda: (lease.release(), lease.release()))
    thread.start()
    thread.join(timeout=1)

    assert not thread.is_alive()
    assert coordinator.snapshot().active_requests == 0
    assert coordinator.snapshot().mode == "normal"


def test_normal_request_leases_are_not_serialized():
    coordinator = DatabaseMaintenanceCoordinator()
    barrier = threading.Barrier(3)
    errors: list[BaseException] = []

    def request(name: str) -> None:
        try:
            with coordinator.acquire_request(name):
                barrier.wait(timeout=1)
                barrier.wait(timeout=1)
        except BaseException as exc:  # pragma: no cover - assertion reports it
            errors.append(exc)

    threads = [threading.Thread(target=request, args=(f"route-{index}",)) for index in range(2)]
    for thread in threads:
        thread.start()

    barrier.wait(timeout=1)
    assert coordinator.snapshot().active_requests == 2
    barrier.wait(timeout=1)
    for thread in threads:
        thread.join(timeout=1)

    assert errors == []
    assert coordinator.snapshot().active_requests == 0


def test_fastapi_sync_dependency_survives_cross_thread_finalization():
    coordinator = DatabaseMaintenanceCoordinator()
    enter_threads: list[int] = []
    finalizer_thread_pairs: list[tuple[int, int]] = []
    observations_lock = threading.Lock()
    app = FastAPI()

    def get_resource():
        lease = coordinator.acquire_request("fastapi-test")
        entry_thread = threading.get_ident()
        with observations_lock:
            enter_threads.append(entry_thread)
        try:
            yield object()
        finally:
            with observations_lock:
                finalizer_thread_pairs.append((entry_thread, threading.get_ident()))
            lease.release()

    @app.get("/db")
    def read_db(_resource=Depends(get_resource)):
        time.sleep(0.002)
        return {"ok": True}

    with TestClient(app) as client:
        for batch in range(10):
            with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
                responses = list(
                    pool.map(lambda _: client.get("/db"), range(batch * 100, (batch + 1) * 100))
                )
            assert all(response.status_code == 200 for response in responses)
            assert coordinator.snapshot().active_requests == 0

    assert len(enter_threads) == len(finalizer_thread_pairs) == 1_000
    assert any(entry != finalizer for entry, finalizer in finalizer_thread_pairs)
    assert coordinator.snapshot().active_requests == 0


def test_maintenance_rejects_new_requests_and_returns_to_normal_after_release():
    coordinator = DatabaseMaintenanceCoordinator()
    maintenance = coordinator.begin_maintenance("restore")

    with pytest.raises(DatabaseAccessUnavailable) as raised:
        coordinator.acquire_request("blocked")
    assert raised.value.code == "database_maintenance"
    assert raised.value.retry_after_seconds == 2
    assert coordinator.try_acquire_request("checkpoint") is None

    maintenance.release()
    with coordinator.acquire_request("allowed"):
        assert coordinator.snapshot().active_requests == 1


def test_fastapi_exception_handler_preserves_maintenance_response_contract():
    coordinator = DatabaseMaintenanceCoordinator()
    app = FastAPI()
    app.add_exception_handler(DatabaseAccessUnavailable, database_access_exception_handler)

    def get_db_lease():
        with coordinator.acquire_request("protected"):
            yield object()

    @app.get("/protected")
    def protected(_lease=Depends(get_db_lease)):
        return {"ok": True}

    maintenance = coordinator.begin_maintenance("restore")
    with TestClient(app) as client:
        response = client.get("/protected")
    maintenance.release()

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "2"
    assert response.json() == {
        "detail": "database maintenance in progress",
        "code": "database_maintenance",
        "retry_after_seconds": 2,
    }


def test_drain_timeout_does_not_enter_maintenance_or_lose_active_lease():
    coordinator = DatabaseMaintenanceCoordinator()
    request = coordinator.acquire_request("slow")

    with pytest.raises(DatabaseDrainTimeout) as raised:
        coordinator.begin_maintenance("restore", drain_timeout_seconds=0.01)

    assert raised.value.active_requests == 1
    assert coordinator.snapshot().mode == "normal"
    assert coordinator.snapshot().active_requests == 1
    request.release()


def test_drain_waits_for_existing_request_and_rejects_new_admission():
    coordinator = DatabaseMaintenanceCoordinator()
    request = coordinator.acquire_request("existing")
    maintenance_ready = threading.Event()

    def begin_maintenance() -> None:
        lease = coordinator.begin_maintenance("restore", drain_timeout_seconds=1)
        maintenance_ready.set()
        lease.release()

    thread = threading.Thread(target=begin_maintenance)
    thread.start()
    deadline = time.monotonic() + 1
    while coordinator.snapshot().mode != "draining" and time.monotonic() < deadline:
        time.sleep(0.001)

    with pytest.raises(DatabaseAccessUnavailable):
        coordinator.acquire_request("new")
    request.release()
    assert maintenance_ready.wait(timeout=1)
    thread.join(timeout=1)
    assert coordinator.snapshot().mode == "normal"


def test_fault_state_is_persistent_and_only_fault_recovery_can_clear_it(tmp_path):
    state_path = tmp_path / "database_fault_state.json"
    coordinator = DatabaseMaintenanceCoordinator(fault_state_path=state_path)
    maintenance = coordinator.begin_maintenance("restore")
    maintenance.mark_faulted("database_restore_rollback_failed")

    assert state_path.exists()
    restarted = DatabaseMaintenanceCoordinator(fault_state_path=state_path)
    assert restarted.snapshot().mode == "faulted"
    assert restarted.snapshot().fault_code == "database_restore_rollback_failed"
    with pytest.raises(DatabaseAccessUnavailable) as raised:
        restarted.acquire_request("ordinary")
    assert raised.value.code == "database_faulted"
    with pytest.raises(DatabaseAccessUnavailable):
        restarted.begin_maintenance("ordinary")

    recovery = restarted.begin_fault_recovery("backup-restore")
    recovery.release()
    assert restarted.snapshot().mode == "normal"
    assert not state_path.exists()


@pytest.mark.parametrize("raise_failure", [False, True])
def test_fault_recovery_context_without_explicit_success_preserves_original_fault(
    tmp_path,
    raise_failure,
):
    state_path = tmp_path / "database_fault_state.json"
    coordinator = DatabaseMaintenanceCoordinator(fault_state_path=state_path)
    coordinator.begin_maintenance("prepare-fault").mark_faulted("original_fault")
    original_state = state_path.read_bytes()

    def unsuccessful_recovery():
        with coordinator.begin_fault_recovery("restore"):
            if raise_failure:
                raise RuntimeError("recovery failed")
            return False

    if raise_failure:
        with pytest.raises(RuntimeError, match="recovery failed"):
            unsuccessful_recovery()
    else:
        assert unsuccessful_recovery() is False

    assert coordinator.snapshot().mode == "faulted"
    assert coordinator.snapshot().fault_code == "original_fault"
    assert state_path.read_bytes() == original_state
    restarted = DatabaseMaintenanceCoordinator(fault_state_path=state_path)
    with pytest.raises(DatabaseAccessUnavailable):
        restarted.acquire_request("after-restart")


@pytest.mark.parametrize("failure_point", ["mkdir", "write", "replace"])
def test_fault_state_persistence_failure_keeps_restart_admission_fail_closed(
    monkeypatch,
    tmp_path,
    failure_point,
):
    import src.data.database_coordination as coordination

    state_path = tmp_path / "database_fault_state.json"
    coordinator = DatabaseMaintenanceCoordinator(fault_state_path=state_path)
    maintenance = coordinator.begin_maintenance("restore")
    guard_path = state_path.with_name(state_path.name + ".guard")
    assert guard_path.exists()

    with monkeypatch.context() as scoped:
        if failure_point == "mkdir":
            original_mkdir = Path.mkdir

            def fail_state_parent_mkdir(path, *args, **kwargs):
                if path == state_path.parent:
                    raise OSError("injected sentinel mkdir failure")
                return original_mkdir(path, *args, **kwargs)

            scoped.setattr(Path, "mkdir", fail_state_parent_mkdir)
        elif failure_point == "write":
            original_open = Path.open
            sentinel_temporary = state_path.with_name(state_path.name + ".tmp")

            def fail_sentinel_write(path, mode="r", *args, **kwargs):
                if path == sentinel_temporary and mode == "wb":
                    raise OSError("injected sentinel write failure")
                return original_open(path, mode, *args, **kwargs)

            scoped.setattr(Path, "open", fail_sentinel_write)
        else:
            original_replace = coordination.os.replace

            def fail_sentinel_replace(source, target):
                if Path(target) == state_path:
                    raise OSError("injected sentinel replace failure")
                return original_replace(source, target)

            scoped.setattr(coordination.os, "replace", fail_sentinel_replace)

        with pytest.raises(DatabaseFaultStatePersistenceError) as raised:
            maintenance.mark_faulted("database_restore_rollback_failed")

    assert raised.value.operation == "sentinel_write"
    assert coordinator.snapshot().mode == "faulted"
    restarted = DatabaseMaintenanceCoordinator(fault_state_path=state_path)
    assert restarted.snapshot().mode == "faulted"
    with pytest.raises(DatabaseAccessUnavailable) as denied:
        restarted.acquire_request("ordinary-after-restart")
    assert denied.value.code == "database_faulted"


def test_checkpoint_admission_is_nonblocking_and_records_timestamp():
    coordinator = DatabaseMaintenanceCoordinator()
    lease = coordinator.try_acquire_request("checkpoint")
    assert lease is not None
    coordinator.record_checkpoint(123.5)
    lease.release()
    assert coordinator.snapshot().last_checkpoint_at == 123.5


def test_beholder_dependency_releases_lease_when_session_creation_fails(monkeypatch):
    import src.api.beholder_routes as routes

    coordinator = DatabaseMaintenanceCoordinator()
    monkeypatch.setattr(routes, "database_coordinator", coordinator)
    monkeypatch.setattr(
        routes,
        "SessionLocal",
        lambda: (_ for _ in ()).throw(RuntimeError("session creation failed")),
    )

    dependency = routes.get_db()
    with pytest.raises(RuntimeError, match="session creation failed"):
        next(dependency)

    assert coordinator.snapshot().active_requests == 0


def test_restore_prevalidation_and_successful_atomic_replace(monkeypatch, tmp_path):
    client, _routes, coordinator, current_db = _restore_client(monkeypatch, tmp_path)

    response = client.post("/api/beholder/backups/restore", json={"slot": 1})

    assert response.status_code == 200, response.text
    assert response.json()["ok"] is True
    assert _read_marker_database(current_db) == "new"
    assert coordinator.snapshot().mode == "normal"
    assert response.json()["previous_snapshot"]


def test_restore_reports_sentinel_clear_failure_without_reverting_database(monkeypatch, tmp_path):
    client, _routes, coordinator, current_db = _restore_client(monkeypatch, tmp_path)
    guard_path = current_db.parent / "database_fault_state.json.guard"
    original_unlink = Path.unlink

    def fail_guard_cleanup(path, *args, **kwargs):
        if path == guard_path:
            raise OSError("injected sentinel clear failure")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_guard_cleanup)

    response = client.post("/api/beholder/backups/restore", json={"slot": 1})

    assert response.status_code == 500
    assert response.json()["code"] == "database_restore_sentinel_clear_failed"
    assert response.json()["database_restored"] is True
    assert "injected sentinel clear failure" in response.json()["sentinel_clear_error"]
    assert response.json()["previous_snapshot"]
    assert _read_marker_database(current_db) == "new"
    assert coordinator.snapshot().mode == "faulted"
    assert coordinator.snapshot().fault_code == "database_fault_state_clear_failed"
    assert guard_path.exists()


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("GET", "/api/beholder/backups", None),
        ("POST", "/api/beholder/backups/restore-preview", {"slot": 1}),
    ],
)
@pytest.mark.parametrize("initial_mode", ["normal", "faulted"])
def test_backup_summary_read_drains_before_concurrent_restore_replace(
    monkeypatch,
    tmp_path,
    method,
    path,
    payload,
    initial_mode,
):
    client, routes, coordinator, current_db = _restore_client(monkeypatch, tmp_path)
    if initial_mode == "faulted":
        coordinator.begin_maintenance("prepare-fault").mark_faulted("test_restore_fault")

    original_summary = routes._db_summary
    summary_open = threading.Event()
    release_summary = threading.Event()

    def blocking_live_summary(path_to_summarize):
        if Path(path_to_summarize) != Path(current_db):
            return original_summary(path_to_summarize)
        with closing(sqlite3.connect(f"file:{current_db}?mode=ro", uri=True)) as connection:
            assert connection.execute("SELECT value FROM marker").fetchone()[0] == "old"
            summary_open.set()
            assert release_summary.wait(timeout=2)
        return original_summary(path_to_summarize)

    monkeypatch.setattr(routes, "_db_summary", blocking_live_summary)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        summary_future = pool.submit(client.request, method, path, json=payload)
        assert summary_open.wait(timeout=1)
        assert coordinator.snapshot().active_requests == 1
        restore_future = pool.submit(
            client.post,
            "/api/beholder/backups/restore",
            json={"slot": 1},
        )
        deadline = time.monotonic() + 1
        while coordinator.snapshot().mode != "draining" and time.monotonic() < deadline:
            time.sleep(0.001)

        assert coordinator.snapshot().mode == "draining"
        assert _read_marker_database(current_db) == "old"
        assert not restore_future.done()
        blocked_response = client.request(method, path, json=payload)
        assert blocked_response.status_code == 503
        assert blocked_response.headers["Retry-After"] == "2"
        assert blocked_response.json()["code"] == "database_maintenance"
        release_summary.set()
        summary_response = summary_future.result(timeout=2)
        restore_response = restore_future.result(timeout=2)

    assert summary_response.status_code == 200
    assert restore_response.status_code == 200
    assert _read_marker_database(current_db) == "new"
    assert coordinator.snapshot().mode == "normal"


def test_backup_summary_routes_reject_reads_during_maintenance(monkeypatch, tmp_path):
    client, _routes, coordinator, _current_db = _restore_client(monkeypatch, tmp_path)
    maintenance = coordinator.begin_maintenance("restore")
    try:
        responses = (
            client.get("/api/beholder/backups"),
            client.post("/api/beholder/backups/restore-preview", json={"slot": 1}),
        )
    finally:
        maintenance.release()

    for response in responses:
        assert response.status_code == 503
        assert response.headers["Retry-After"] == "2"
        assert response.json() == {
            "detail": "database maintenance in progress",
            "code": "database_maintenance",
            "retry_after_seconds": 2,
        }


def test_restore_checkpoint_failure_leaves_live_database_unchanged(monkeypatch, tmp_path):
    client, routes, coordinator, current_db = _restore_client(monkeypatch, tmp_path)
    monkeypatch.setattr(
        routes,
        "_checkpoint_live_database",
        lambda _path: (_ for _ in ()).throw(RuntimeError("checkpoint failed")),
    )

    response = client.post("/api/beholder/backups/restore", json={"slot": 1})

    assert response.status_code == 500
    assert response.json()["code"] == "database_restore_failed"
    assert _read_marker_database(current_db) == "old"
    assert coordinator.snapshot().mode == "normal"


def test_restore_aborts_on_busy_wal_checkpoint_before_sidecar_removal_or_replace(
    monkeypatch,
    tmp_path,
):
    client, _routes, coordinator, current_db = _restore_client(monkeypatch, tmp_path)
    writer = sqlite3.connect(current_db)
    reader = sqlite3.connect(current_db)
    try:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower() == "wal"
        writer.execute("CREATE TABLE wal_probe (value TEXT NOT NULL)")
        writer.execute("INSERT INTO wal_probe (value) VALUES ('held-reader')")
        writer.commit()
        reader.execute("BEGIN")
        assert reader.execute("SELECT value FROM wal_probe").fetchone()[0] == "held-reader"
        checkpoint = writer.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
        assert checkpoint is not None and checkpoint[0] == 0
        before_hash = _sha256(current_db)
        wal_path = Path(str(current_db) + "-wal")
        shm_path = Path(str(current_db) + "-shm")
        assert wal_path.exists()
        assert shm_path.exists()

        response = client.post("/api/beholder/backups/restore", json={"slot": 1})

        assert response.status_code == 500
        assert response.json()["code"] == "database_restore_failed"
        assert "미조정 연결" in response.json()["restore_error"]
        assert _sha256(current_db) == before_hash
        assert _read_marker_database(current_db) == "old"
        assert wal_path.exists()
        assert shm_path.exists()
        assert coordinator.snapshot().mode == "normal"
    finally:
        reader.close()
        writer.close()


def test_strict_restore_preparation_order_is_create_all_migration_integrity(
    monkeypatch,
):
    import src.api.beholder_routes as routes

    calls: list[str] = []
    monkeypatch.setattr(routes.engine, "dispose", lambda: calls.append("dispose"))
    monkeypatch.setattr(
        routes.Base.metadata,
        "create_all",
        lambda *, bind: calls.append("create_all"),
    )
    monkeypatch.setattr(
        routes,
        "auto_migrate_database",
        lambda *, strict: calls.append(f"migration:{strict}"),
    )
    monkeypatch.setattr(
        routes,
        "_require_valid_sqlite_backup",
        lambda path: calls.append(f"integrity:{path}"),
    )

    routes._strict_prepare_live_database()

    assert calls == [
        "dispose",
        "create_all",
        "migration:True",
        f"integrity:{routes.db_path}",
    ]


def test_restore_validation_failure_rolls_back_previous_database(monkeypatch, tmp_path):
    client, routes, coordinator, current_db = _restore_client(monkeypatch, tmp_path)
    calls = 0

    def fail_new_database_once():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("strict migration failed")
        routes._require_valid_sqlite_backup(current_db)

    monkeypatch.setattr(routes, "_strict_prepare_live_database", fail_new_database_once)

    response = client.post("/api/beholder/backups/restore", json={"slot": 1})

    assert response.status_code == 500
    assert response.json()["code"] == "database_restore_rolled_back"
    assert _read_marker_database(current_db) == "old"
    assert calls == 2
    assert coordinator.snapshot().mode == "normal"


def test_restore_and_rollback_failure_persists_fault_but_allows_backup_recovery(
    monkeypatch,
    tmp_path,
):
    client, routes, coordinator, current_db = _restore_client(monkeypatch, tmp_path)
    monkeypatch.setattr(
        routes,
        "_strict_prepare_live_database",
        lambda: (_ for _ in ()).throw(RuntimeError("database cannot be prepared")),
    )

    failed = client.post("/api/beholder/backups/restore", json={"slot": 1})

    assert failed.status_code == 500
    assert failed.json()["code"] == "database_restore_rollback_failed"
    assert coordinator.snapshot().mode == "faulted"
    assert (tmp_path / "homework_helper_data" / "database_fault_state.json").exists()
    assert client.get("/api/beholder/backups").status_code == 200
    assert client.post("/api/beholder/backups/restore-preview", json={"slot": 1}).status_code == 200

    monkeypatch.setattr(
        routes,
        "_strict_prepare_live_database",
        lambda: routes._require_valid_sqlite_backup(current_db),
    )
    recovered = client.post("/api/beholder/backups/restore", json={"slot": 1})

    assert recovered.status_code == 200
    assert coordinator.snapshot().mode == "normal"
    assert not (tmp_path / "homework_helper_data" / "database_fault_state.json").exists()
    assert _read_marker_database(current_db) == "new"


def test_restore_rollback_error_contract_survives_fault_sentinel_write_failure(
    monkeypatch,
    tmp_path,
):
    client, routes, coordinator, _current_db = _restore_client(monkeypatch, tmp_path)
    monkeypatch.setattr(
        routes,
        "_strict_prepare_live_database",
        lambda: (_ for _ in ()).throw(RuntimeError("database cannot be prepared")),
    )
    monkeypatch.setattr(
        coordinator,
        "_write_fault_state",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("sentinel unavailable")),
    )

    response = client.post("/api/beholder/backups/restore", json={"slot": 1})

    assert response.status_code == 500
    assert response.json()["code"] == "database_restore_rollback_failed"
    assert coordinator.snapshot().mode == "faulted"
    restarted = DatabaseMaintenanceCoordinator(
        fault_state_path=tmp_path / "homework_helper_data" / "database_fault_state.json"
    )
    assert restarted.snapshot().mode == "faulted"


def _damage_live_database(coordinator, current_db):
    originals = {
        "": b"damaged SQLite original\x00\xff",
        "-wal": b"original WAL bytes\x00\xfe",
        "-shm": b"original SHM bytes\x00\xfd",
    }
    for suffix, content in originals.items():
        Path(str(current_db) + suffix).write_bytes(content)
    coordinator.begin_maintenance("prepare-fault").mark_faulted("original_fault")
    return originals


def _assert_original_files(path, originals):
    for suffix, content in originals.items():
        assert Path(str(path) + suffix).read_bytes() == content


def test_faulted_damaged_database_restores_valid_backup_and_preserves_raw_originals(
    monkeypatch,
    tmp_path,
):
    client, routes, coordinator, current_db = _restore_client(monkeypatch, tmp_path)
    originals = _damage_live_database(coordinator, current_db)
    copy_sqlite = routes._copy_sqlite_database

    def copy_backup_only(source, target):
        assert Path(source) != current_db
        assert "before_beholder_restore" not in str(source)
        copy_sqlite(source, target)

    monkeypatch.setattr(routes, "_copy_sqlite_database", copy_backup_only)
    monkeypatch.setattr(
        routes,
        "_checkpoint_live_database",
        lambda _path: pytest.fail("faulted original must not require a SQLite checkpoint"),
    )

    response = client.post("/api/beholder/backups/restore", json={"slot": 1})

    assert response.status_code == 200, response.text
    _assert_original_files(response.json()["previous_snapshot"], originals)
    assert _read_marker_database(current_db) == "new"
    assert not Path(str(current_db) + "-wal").exists()
    assert not Path(str(current_db) + "-shm").exists()
    assert coordinator.snapshot().mode == "normal"
    restarted = DatabaseMaintenanceCoordinator(
        fault_state_path=current_db.parent / "database_fault_state.json"
    )
    assert restarted.snapshot().mode == "normal"


@pytest.mark.parametrize("failure_suffix", ["", "-wal", "-shm"])
def test_faulted_original_preservation_failure_does_not_replace_or_unblock_database(
    monkeypatch,
    tmp_path,
    failure_suffix,
):
    client, _routes, coordinator, current_db = _restore_client(monkeypatch, tmp_path)
    originals = _damage_live_database(coordinator, current_db)
    original_open = Path.open

    def fail_snapshot_open(path, mode="r", *args, **kwargs):
        if "before_beholder_restore" in path.name and mode == "wb" and str(path).endswith(
            ".db" + failure_suffix
        ):
            raise OSError("original preservation failed")
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_snapshot_open)
    response = client.post("/api/beholder/backups/restore", json={"slot": 1})

    assert response.status_code == 500
    assert response.json()["code"] == "database_restore_failed"
    assert "original preservation failed" in response.json()["restore_error"]
    _assert_original_files(current_db, originals)
    assert coordinator.snapshot().mode == "faulted"
    assert coordinator.snapshot().fault_code == "original_fault"
    restarted = DatabaseMaintenanceCoordinator(
        fault_state_path=current_db.parent / "database_fault_state.json"
    )
    assert restarted.snapshot().mode == "faulted"
    assert client.get("/api/beholder/backups").status_code == 200
    assert client.post("/api/beholder/backups/restore-preview", json={"slot": 1}).status_code == 200


def test_faulted_replace_failure_preserves_live_original_and_sidecars(monkeypatch, tmp_path):
    client, routes, coordinator, current_db = _restore_client(monkeypatch, tmp_path)
    originals = _damage_live_database(coordinator, current_db)
    original_replace = routes.os.replace

    def fail_live_replace(source, target):
        if Path(target) == current_db:
            raise OSError("live replacement failed")
        return original_replace(source, target)

    monkeypatch.setattr(routes.os, "replace", fail_live_replace)
    response = client.post("/api/beholder/backups/restore", json={"slot": 1})

    assert response.status_code == 500
    assert response.json()["code"] == "database_restore_failed"
    _assert_original_files(current_db, originals)
    assert coordinator.snapshot().mode == "faulted"


def test_faulted_restore_validation_failure_rolls_back_raw_original_but_keeps_protection(
    monkeypatch,
    tmp_path,
):
    client, routes, coordinator, current_db = _restore_client(monkeypatch, tmp_path)
    originals = _damage_live_database(coordinator, current_db)
    preparation_calls = []

    def reject_new_database():
        preparation_calls.append(_read_marker_database(current_db))
        raise RuntimeError("restored database preparation failed")

    monkeypatch.setattr(routes, "_strict_prepare_live_database", reject_new_database)
    response = client.post("/api/beholder/backups/restore", json={"slot": 1})

    assert response.status_code == 500
    assert response.json()["code"] == "database_restore_rolled_back"
    assert preparation_calls == ["new"]
    _assert_original_files(current_db, originals)
    preserved = list(current_db.parent.glob("app_data.before_beholder_restore.*.db"))
    assert len(preserved) == 1
    _assert_original_files(preserved[0], originals)
    assert coordinator.snapshot().mode == "faulted"
    assert coordinator.snapshot().fault_code == "original_fault"
    restarted = DatabaseMaintenanceCoordinator(
        fault_state_path=current_db.parent / "database_fault_state.json"
    )
    assert restarted.snapshot().mode == "faulted"
    with pytest.raises(DatabaseAccessUnavailable):
        coordinator.acquire_request("ordinary-after-raw-rollback")


def test_faulted_raw_rollback_failure_keeps_original_snapshot_and_restart_protection(
    monkeypatch,
    tmp_path,
):
    client, routes, coordinator, current_db = _restore_client(monkeypatch, tmp_path)
    originals = _damage_live_database(coordinator, current_db)
    monkeypatch.setattr(
        routes,
        "_strict_prepare_live_database",
        lambda: (_ for _ in ()).throw(RuntimeError("restored database preparation failed")),
    )
    original_replace = routes.os.replace

    def fail_raw_rollback(source, target):
        if "rollback_tmp" in str(source):
            raise OSError("raw rollback failed")
        return original_replace(source, target)

    monkeypatch.setattr(routes.os, "replace", fail_raw_rollback)
    response = client.post("/api/beholder/backups/restore", json={"slot": 1})

    assert response.status_code == 500
    assert response.json()["code"] == "database_restore_rollback_failed"
    assert "raw rollback failed" in response.json()["rollback_error"]
    preserved = list(current_db.parent.glob("app_data.before_beholder_restore.*.db"))
    assert len(preserved) == 1
    _assert_original_files(preserved[0], originals)
    assert coordinator.snapshot().mode == "faulted"
    restarted = DatabaseMaintenanceCoordinator(
        fault_state_path=current_db.parent / "database_fault_state.json"
    )
    assert restarted.snapshot().mode == "faulted"


def test_faulted_restore_sentinel_clear_failure_keeps_new_database_blocked(
    monkeypatch,
    tmp_path,
):
    client, _routes, coordinator, current_db = _restore_client(monkeypatch, tmp_path)
    originals = _damage_live_database(coordinator, current_db)
    state_path = current_db.parent / "database_fault_state.json"
    original_unlink = Path.unlink

    def fail_fault_cleanup(path, *args, **kwargs):
        if path == state_path:
            raise OSError("fault state cleanup failed")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_fault_cleanup)
    response = client.post("/api/beholder/backups/restore", json={"slot": 1})

    assert response.status_code == 500
    assert response.json()["code"] == "database_restore_sentinel_clear_failed"
    assert response.json()["database_restored"] is True
    assert _read_marker_database(current_db) == "new"
    _assert_original_files(response.json()["previous_snapshot"], originals)
    with pytest.raises(DatabaseAccessUnavailable):
        coordinator.acquire_request("after-sentinel-clear-failure")
    assert DatabaseMaintenanceCoordinator(fault_state_path=state_path).snapshot().mode == "faulted"


def test_restore_preparation_failure_never_replaces_live_database(monkeypatch, tmp_path):
    client, routes, coordinator, current_db = _restore_client(monkeypatch, tmp_path)
    monkeypatch.setattr(routes, "_prepare_restore_runtime", lambda: False)
    before = _sha256(current_db)
    response = client.post("/api/beholder/backups/restore", json={"slot": 1})
    assert response.status_code == 409
    assert response.json()["code"] == "database_restore_runtime_not_ready"
    assert _sha256(current_db) == before
    assert coordinator.snapshot().mode == "normal"


def test_corrupt_startup_keeps_backup_slots_and_recovery_protection(monkeypatch, tmp_path):
    import src.data.database as database
    from src.data.database_coordination import DatabaseMaintenanceCoordinator
    current = tmp_path / "app_data.db"
    current.write_bytes(b"broken database header")
    backups = tmp_path / "backups"
    backups.mkdir()
    for slot in range(1, 4):
        _write_marker_database(backups / f"app_data.backup.{slot}.db", f"healthy-{slot}")
    before = {p.name: _sha256(p) for p in backups.iterdir()}
    monkeypatch.setattr(database, "db_path", str(current))
    monkeypatch.setattr(database, "base_dir", str(tmp_path))
    monkeypatch.setattr(database, "auto_migrate_database", lambda **kw: pytest.fail("migration on damaged DB"))
    coordinator = DatabaseMaintenanceCoordinator(fault_state_path=tmp_path / "fault.json")
    assert not database.prepare_database_startup(coordinator)
    assert coordinator.snapshot().mode == "faulted"
    for _ in range(3):
        assert not database.backup_database()
        assert not database.prepare_database_startup(coordinator)
    assert {p.name: _sha256(p) for p in backups.iterdir()} == before
    assert current.read_bytes() == b"broken database header"


def test_validated_new_backup_precedes_rotation(monkeypatch, tmp_path):
    import src.data.database as database
    current = tmp_path / "app_data.db"
    _write_marker_database(current, "current")
    backups = tmp_path / "backups"
    backups.mkdir()
    _write_marker_database(backups / "app_data.backup.1.db", "old")
    monkeypatch.setattr(database, "db_path", str(current))
    monkeypatch.setattr(database, "base_dir", str(tmp_path))
    assert database.backup_database()
    assert _read_marker_database(backups / "app_data.backup.1.db") == "current"
    assert _read_marker_database(backups / "app_data.backup.2.db") == "old"


def test_fresh_and_existing_valid_database_startup_use_real_migrations(monkeypatch, tmp_path):
    from sqlalchemy import create_engine
    import src.data.database as database
    from src.data.database_coordination import DatabaseMaintenanceCoordinator
    current = tmp_path / "app_data.db"
    test_engine = create_engine(f"sqlite:///{current}")
    monkeypatch.setattr(database, "db_path", str(current))
    monkeypatch.setattr(database, "base_dir", str(tmp_path))
    monkeypatch.setattr(database, "engine", test_engine)
    coordinator = DatabaseMaintenanceCoordinator(fault_state_path=tmp_path / "fault.json")
    try:
        assert database.prepare_database_startup(coordinator)
        assert coordinator.snapshot().mode == "normal"
        assert database.prepare_database_startup(coordinator)
        assert (tmp_path / "backups/app_data.backup.1.db").exists()
    finally: test_engine.dispose()


def test_page_damage_that_passes_select_one_still_blocks_startup(monkeypatch, tmp_path):
    import src.data.database as database
    from src.data.database_coordination import DatabaseMaintenanceCoordinator
    current=tmp_path/'app_data.db'
    _write_marker_database(current,'healthy before page damage')
    raw=bytearray(current.read_bytes())
    page_size=int.from_bytes(raw[16:18],'big')
    raw[page_size]=255  # Invalid second-page btree type; the database header is intact.
    current.write_bytes(raw)
    with closing(sqlite3.connect(current)) as conn:
        assert conn.execute('SELECT 1').fetchone()==(1,)
    monkeypatch.setattr(database,'db_path',str(current))
    coordinator=DatabaseMaintenanceCoordinator(fault_state_path=tmp_path/'fault.json')
    assert not database.prepare_database_startup(coordinator)
    assert coordinator.snapshot().mode=='faulted'
    assert current.read_bytes()==raw
