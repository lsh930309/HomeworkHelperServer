from src.core.remote_local_store import RemoteLocalStore


def test_remote_local_store_writes_manifest_and_rotating_backup(tmp_path):
    store = RemoteLocalStore(root=tmp_path / "remote", legacy_root=tmp_path / "legacy", max_backups=2)

    store.write_json("remote_power_config.json", {"ssh_host": "host-a"})
    store.write_json("remote_power_config.json", {"ssh_host": "host-b"})

    assert store.read_json("remote_power_config.json", {})["ssh_host"] == "host-b"
    report = store.integrity_report()
    assert report["ok"] is True
    assert "remote_power_config.json" in report["manifest"]["files"]
    assert list((tmp_path / "remote" / "backups").glob("remote_power_config.json.*.bak"))


def test_remote_local_store_migrates_legacy_file(tmp_path):
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "remote_devices.json").write_text('{"schema_version": 1, "devices": [{"id":"d"}]}', encoding="utf-8")
    store = RemoteLocalStore(root=tmp_path / "remote", legacy_root=legacy)

    path = store.path("remote_devices.json")

    assert path.exists()
    assert store.read_json("remote_devices.json", {})["devices"][0]["id"] == "d"
    assert store.integrity_report()["ok"] is True
