import json

import pytest

import build
import build_android_remote as android_build
from src.core.tailscale import TailscalePeer, TailscaleSnapshot


def _android_config(version: str = "0.1.0", build_number: int = 7) -> dict:
    return {
        "schema": 1,
        "targets": {
            "android-client": {"version": version, "build": build_number},
        },
    }


def test_candidate_android_version_adds_missing_target_without_initial_build_bump():
    config = {"schema": 1, "targets": {"macos-client": {"version": "0.2.0", "build": 3}}}

    candidate = android_build.candidate_android_version_config(config, "build")

    assert candidate["targets"]["android-client"] == {"version": "0.1.0", "build": 1}
    assert "android-client" not in config["targets"]


def test_android_version_code_and_gradle_command_use_release_version():
    info = build.make_version_info("android-client", _android_config("0.1.2", 34), git_hash="abc1234", dirty=False)
    keystore = android_build.PROJECT_ROOT / "local-artifacts/android-signing/test-debug.keystore"

    assert android_build.android_version_code(info) == 1_020_034
    assert android_build.android_release_apk_path(info).name == "HomeworkHelperRemoteAndroid_v0.1.2_b34_gabc1234.apk"
    assert android_build.create_gradle_assemble_command(info, debug_keystore=keystore) == [
        "./gradlew",
        ":app:assembleRelease",
        "--stacktrace",
        "-Phomeworkhelper.android.versionName=0.1.2",
        "-Phomeworkhelper.android.versionCode=1020034",
        f"-Phomeworkhelper.android.debugStoreFile={keystore}",
        "-Phomeworkhelper.android.debugStorePassword=android",
        "-Phomeworkhelper.android.debugKeyAlias=androiddebugkey",
        "-Phomeworkhelper.android.debugKeyPassword=android",
    ]


def test_gradle_command_can_seed_default_remote_agent_url():
    info = build.make_version_info("android-client", _android_config("0.1.2", 34), git_hash="abc1234", dirty=False)

    command = android_build.create_gradle_assemble_command(info, default_remote_base_url="100.64.0.9")

    assert "-Phomeworkhelper.android.defaultRemoteBaseUrl=http://100.64.0.9:8000" in command


def test_gradle_command_accepts_public_https_remote_agent_url():
    info = build.make_version_info("android-client", _android_config("0.1.2", 34), git_hash="abc1234", dirty=False)

    command = android_build.create_gradle_assemble_command(info, default_remote_base_url="https://home.example.com")

    assert "-Phomeworkhelper.android.defaultRemoteBaseUrl=https://home.example.com" in command


def test_gradle_command_rejects_public_http_remote_agent_url():
    info = build.make_version_info("android-client", _android_config("0.1.2", 34), git_hash="abc1234", dirty=False)

    with pytest.raises(RuntimeError, match="HTTPS"):
        android_build.create_gradle_assemble_command(info, default_remote_base_url="http://home.example.com")


def test_remote_base_url_normalization_adds_fixed_scheme_and_port():
    assert android_build.normalize_remote_base_url("") == ""
    assert android_build.normalize_remote_base_url("100.64.0.9") == "http://100.64.0.9:8000"
    assert android_build.normalize_remote_base_url("host.tailnet.ts.net:9000") == "http://host.tailnet.ts.net:9000"
    assert android_build.normalize_remote_base_url("http://host.tailnet.ts.net") == "http://host.tailnet.ts.net:8000"
    assert android_build.normalize_remote_base_url("https://home.example.com") == "https://home.example.com"


def test_parse_and_choose_adb_mdns_ports_prefers_requested_ip_then_single_fallback():
    output = """
List of discovered mdns services
adb-phone-a      _adb-tls-pairing._tcp    192.168.1.10:37123
adb-phone-a      _adb-tls-connect._tcp    192.168.1.10:42501
adb-phone-b      _adb-tls-connect._tcp    100.64.0.7:40111
"""
    services = android_build.parse_adb_mdns_services(output)

    assert android_build.choose_mdns_port(services, android_build.ADB_TLS_CONNECT_SERVICE, "100.64.0.7") == 40111
    assert android_build.choose_mdns_port(services, android_build.ADB_TLS_PAIRING_SERVICE, "100.64.0.7") == 37123
    assert android_build.choose_mdns_port(services, android_build.ADB_TLS_CONNECT_SERVICE, "100.64.0.8") is None


def _snapshot(peers: tuple[TailscalePeer, ...]) -> TailscaleSnapshot:
    return TailscaleSnapshot(
        installed=True,
        running=True,
        backend_state="Running",
        self_ips=("100.64.0.1",),
        self_hostname="macbook",
        peers=peers,
        message="ok",
    )


def test_tailscale_peer_selection_uses_single_android_even_when_offline():
    peer = TailscalePeer(
        hostname="s25-ultra",
        dns_name="s25-ultra.tail.ts.net.",
        ips=("100.102.217.35",),
        online=False,
        os="android",
    )

    assert android_build.select_tailscale_peer(_snapshot((peer,))).primary_ipv4() == "100.102.217.35"


def test_tailscale_peer_selection_requires_selector_for_multiple_android_devices():
    snapshot = _snapshot(
        (
            TailscalePeer("s25-ultra", "s25-ultra.tail.ts.net.", ("100.102.217.35",), False, "android"),
            TailscalePeer("tablet", "tablet.tail.ts.net.", ("100.102.217.36",), True, "android"),
        )
    )

    try:
        android_build.select_tailscale_peer(snapshot)
    except RuntimeError as exc:
        assert "--tailscale-device" in str(exc)
        assert "s25-ultra" in str(exc)
        assert "tablet" in str(exc)
    else:
        raise AssertionError("multiple Android peers should require an explicit selector")


def test_tailscale_peer_selection_accepts_hostname_dns_node_id_or_ip_selector():
    peer = TailscalePeer(
        hostname="s25-ultra",
        dns_name="s25-ultra.tail.ts.net.",
        ips=("100.102.217.35",),
        online=False,
        os="android",
        node_id="node-abc",
    )
    snapshot = _snapshot((peer,))

    for selector in ["s25-ultra", "s25-ultra.tail.ts.net", "node-abc", "100.102.217.35"]:
        assert android_build.select_tailscale_peer(snapshot, selector).primary_ipv4() == "100.102.217.35"


def test_default_remote_base_url_resolves_tailscale_host_selector(monkeypatch):
    snapshot = _snapshot(
        (
            TailscalePeer("gaming-host", "gaming-host.tail.ts.net.", ("100.64.0.9",), True, "windows"),
            TailscalePeer("s25-ultra", "s25-ultra.tail.ts.net.", ("100.102.217.35",), True, "android"),
        )
    )
    monkeypatch.setattr(android_build, "tailscale_status", lambda **_kwargs: snapshot)

    assert android_build.resolve_default_remote_base_url(None, "gaming-host") == "http://100.64.0.9:8000"


def test_default_remote_base_url_rejects_ambiguous_sources():
    with pytest.raises(RuntimeError, match="동시에"):
        android_build.resolve_default_remote_base_url("100.64.0.9", "gaming-host")


def test_install_signature_preflight_allows_matching_certificates(monkeypatch, tmp_path):
    apk = tmp_path / "candidate.apk"
    apk.write_text("apk", encoding="utf-8")
    monkeypatch.setattr(android_build, "installed_apk_certificate_sha256", lambda *_args, **_kwargs: "abc123")
    monkeypatch.setattr(android_build, "apk_certificate_sha256", lambda _apk: "abc123")

    assert android_build.preflight_install_signature("adb", "serial", apk) == "match"


def test_install_signature_preflight_blocks_mismatch_by_default(monkeypatch, tmp_path):
    apk = tmp_path / "candidate.apk"
    apk.write_text("apk", encoding="utf-8")
    calls = []
    monkeypatch.setattr(android_build, "installed_apk_certificate_sha256", lambda *_args, **_kwargs: "old")
    monkeypatch.setattr(android_build, "apk_certificate_sha256", lambda _apk: "new")
    monkeypatch.setattr(android_build, "_run", lambda command, **_kwargs: calls.append(command))

    with pytest.raises(RuntimeError, match="서명이 다릅니다"):
        android_build.preflight_install_signature("adb", "serial", apk)

    assert calls == []


def test_install_signature_preflight_can_uninstall_on_explicit_mismatch_flag(monkeypatch, tmp_path):
    apk = tmp_path / "candidate.apk"
    apk.write_text("apk", encoding="utf-8")
    calls = []
    monkeypatch.setattr(android_build, "installed_apk_certificate_sha256", lambda *_args, **_kwargs: "old")
    monkeypatch.setattr(android_build, "apk_certificate_sha256", lambda _apk: "new")
    monkeypatch.setattr(android_build, "_run", lambda command, **_kwargs: calls.append(command))

    result = android_build.preflight_install_signature(
        "adb",
        "serial",
        apk,
        uninstall_on_signature_mismatch=True,
    )

    assert result == "uninstalled"
    assert calls == [["adb", "-s", "serial", "uninstall", android_build.PACKAGE_NAME]]


def test_main_does_not_save_version_when_install_fails(monkeypatch, tmp_path):
    version_file = tmp_path / "build.version.json"
    version_file.write_text(
        json.dumps({"schema": 1, "targets": {"android-client": {"version": "0.1.0", "build": 1}}}),
        encoding="utf-8",
    )
    apk = tmp_path / "candidate.apk"
    apk.write_text("apk", encoding="utf-8")

    monkeypatch.setattr(build, "git_short_hash", lambda *args, **kwargs: "abc1234")
    monkeypatch.setattr(build, "git_worktree_dirty", lambda: False)
    monkeypatch.setattr(android_build, "archive_release_artifacts", lambda **_kwargs: [])
    monkeypatch.setattr(android_build, "build_android_apk", lambda _version_info, **_kwargs: None)
    monkeypatch.setattr(android_build, "copy_release_apk", lambda _version_info: apk)
    monkeypatch.setattr(android_build, "check_release_apk", lambda _apk, _version_info: None)
    monkeypatch.setattr(android_build, "resolve_adb", lambda _explicit: "adb")
    monkeypatch.setattr(android_build, "prepare_wireless_adb", lambda _args, _adb: "serial")
    monkeypatch.setattr(android_build, "preflight_install_signature", lambda *_args, **_kwargs: "match")
    monkeypatch.setattr(android_build, "install_apk", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("install failed")))

    result = android_build.main(["--version-file", str(version_file), "--device-ip", "100.102.217.35"])

    assert result == 1
    config = json.loads(version_file.read_text(encoding="utf-8"))
    assert config["targets"]["android-client"]["build"] == 1


def test_android_archive_moves_only_android_apks_into_target_bucket(tmp_path, monkeypatch):
    release_dir = tmp_path / "release"
    archives_dir = release_dir / "archives"
    release_dir.mkdir()
    monkeypatch.setattr(build, "RELEASE_DIR", release_dir)
    monkeypatch.setattr(build, "ARCHIVES_DIR", archives_dir)

    android_apk = release_dir / "HomeworkHelperRemoteAndroid_v0.1.0_b1_gabc1234.apk"
    macos_pkg = release_dir / "HomeworkHelperRemote_v0.2.0_b1_gabc1234.pkg"
    android_apk.write_text("apk", encoding="utf-8")
    macos_pkg.write_text("pkg", encoding="utf-8")

    archived = android_build.archive_release_artifacts(
        targets={android_build.ANDROID_TARGET},
        archive_keep=10,
        archive_days=90,
        prune_archives=False,
    )

    assert len(archived) == 1
    assert archived[0].relative_to(archives_dir).as_posix().startswith("android-client/apk/")
    assert not android_apk.exists()
    assert macos_pkg.exists()
