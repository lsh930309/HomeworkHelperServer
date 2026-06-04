import threading

from src.core import remote_debug_log
from src.core.remote_local_store import RemoteLocalStore


def test_remote_local_store_writes_manifest_and_rotating_backup(tmp_path):
    store = RemoteLocalStore(root=tmp_path / "remote", legacy_root=tmp_path / "legacy", max_backups=2)

    store.write_json("remote_devices.json", {"devices": [{"id": "host-a"}]})
    store.write_json("remote_devices.json", {"devices": [{"id": "host-b"}]})

    assert store.read_json("remote_devices.json", {})["devices"][0]["id"] == "host-b"
    report = store.integrity_report()
    assert report["ok"] is True
    assert "remote_devices.json" in report["manifest"]["files"]
    assert list((tmp_path / "remote" / "backups").glob("remote_devices.json.*.bak"))


def test_remote_local_store_migrates_legacy_file(tmp_path):
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "remote_devices.json").write_text('{"schema_version": 1, "devices": [{"id":"d"}]}', encoding="utf-8")
    store = RemoteLocalStore(root=tmp_path / "remote", legacy_root=legacy)

    path = store.path("remote_devices.json")

    assert path.exists()
    assert store.read_json("remote_devices.json", {})["devices"][0]["id"] == "d"
    assert store.integrity_report()["ok"] is True


def test_remote_local_store_uses_unique_atomic_temp_files_under_concurrency(tmp_path):
    store = RemoteLocalStore(root=tmp_path / "remote", legacy_root=tmp_path / "legacy", max_backups=20)
    errors: list[BaseException] = []

    def write(index: int) -> None:
        try:
            store.write_json(f"remote_{index % 3}.json", {"index": index})
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=write, args=(index,)) for index in range(24)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    report = store.integrity_report()
    assert report["ok"] is True
    assert set(report["manifest"]["files"]) == {"remote_0.json", "remote_1.json", "remote_2.json"}


def test_remote_debug_log_ignores_unserializable_payload(tmp_path, monkeypatch):
    log_path = tmp_path / "HomeworkHelperRemoteHost.log"
    monkeypatch.setattr(remote_debug_log, "load_config", lambda: {"enabled": True, "path": str(log_path)})

    remote_debug_log.write_event("bad_payload", payload=object())

    assert not log_path.exists()
