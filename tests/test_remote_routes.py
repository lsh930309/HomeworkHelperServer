import os
import tempfile
from pathlib import Path

os.environ["HOME"] = "/tmp/homeworkhelper-tests"
Path(os.environ["HOME"]).mkdir(parents=True, exist_ok=True)

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.remote_routes import create_remote_router
from src.core.remote_pairing import RemoteDeviceRegistry
from src.core.remote_power import ConfigurablePowerController, RemotePowerConfig
from src.data import models


class _FakeLauncher:
    def __init__(self):
        self.targets: list[str] = []

    def launch_process(self, target: str) -> bool:
        self.targets.append(target)
        return True


class _FakeAuditor:
    def __init__(self):
        self.events: list[dict] = []

    def record(self, **event):
        self.events.append(event)
        return event


def _client_with_seed(
    *,
    processes=None,
    shortcuts=None,
    sessions=None,
    incidents=None,
    game_links=None,
    mobile_sessions=None,
    auth_token=None,
    device_registry=None,
    power_controller=None,
    require_auth=False,
    client_address=("testclient", 50000),
    power_config_path=None,
):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    models.Base.metadata.create_all(bind=engine)
    db = TestingSession()
    try:
        db.add(models.GlobalSettings(id=1, run_as_admin=False))
        for process in processes or []:
            db.add(process)
        for shortcut in shortcuts or []:
            db.add(shortcut)
        for session in sessions or []:
            db.add(session)
        for incident in incidents or []:
            db.add(incident)
        for game_link in game_links or []:
            db.add(game_link)
        for mobile_session in mobile_sessions or []:
            db.add(mobile_session)
        db.commit()
    finally:
        db.close()

    fake_launcher = _FakeLauncher()
    fake_auditor = _FakeAuditor()
    device_registry = device_registry or RemoteDeviceRegistry(
        path=Path(tempfile.mkdtemp(prefix="hh-remote-devices-")) / "remote_devices.json"
    )
    opened_urls: list[str] = []

    def get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(
        create_remote_router(
            get_db,
            launcher_factory=lambda _run_as_admin: fake_launcher,
            shortcut_opener=lambda url: opened_urls.append(url) is None or True,
            auditor=fake_auditor,
            device_registry=device_registry,
            power_controller=power_controller,
            auth_token=auth_token,
            require_auth=require_auth,
            now=lambda: 1778497000.0,
            power_config_path=power_config_path,
        )
    )
    return TestClient(app, client=client_address), fake_launcher, opened_urls, fake_auditor, device_registry


def test_remote_status_reports_counts_and_safe_default_power_capability():
    client, _launcher, _opened_urls, _auditor, _registry = _client_with_seed(
        processes=[models.Process(id="game-a", name="Game A", monitoring_path="/game.exe", launch_path="/game.url")],
        shortcuts=[models.WebShortcut(id="web-a", name="Web A", url="https://example.com")],
    )

    response = client.get("/remote/status")

    assert response.status_code == 200
    body = response.json()
    assert body["remote_api_version"] == "0.1.8"
    assert body["counts"]["processes"] == 1
    assert body["counts"]["shortcuts"] == 1
    assert body["capabilities"]["process_launch"] is True
    assert body["capabilities"]["shortcut_open"] is True
    assert body["capabilities"]["dashboard_summary"] is True
    assert body["capabilities"]["beholder_incidents"] is True
    assert body["capabilities"]["game_links"] is True
    assert body["capabilities"]["mobile_sessions"] is True
    assert body["capabilities"]["power_config"] is True
    assert body["capabilities"]["power_control"] is False
    assert body["capabilities"]["auth_required"] is False
    assert body["capabilities"]["pairing"] is True
    assert body["power"]["configured"] is False
    assert body["power"]["state"] == "unknown"
    assert body["power"]["status"] == "unknown"
    assert body["power"]["supported_actions"] == []
    assert body["power"]["target_host"] == ""


def test_remote_launch_uses_shortcut_preference_and_existing_launcher_logic_boundary():
    client, launcher, _opened_urls, auditor, _registry = _client_with_seed(
        processes=[
            models.Process(
                id="game-a",
                name="Game A",
                monitoring_path="/Applications/Game.app",
                launch_path="/Users/me/Desktop/Game.url",
                preferred_launch_type="shortcut",
            )
        ]
    )

    response = client.post("/remote/processes/game-a/launch", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert body["command"] == "process.launch.shortcut"
    assert body["target"] == "/Users/me/Desktop/Game.url"
    assert launcher.targets == ["/Users/me/Desktop/Game.url"]
    assert auditor.events[-1]["command"] == "process.launch.shortcut"
    assert auditor.events[-1]["accepted"] is True


def test_remote_dashboard_summary_exposes_read_only_analytics_under_remote_auth_boundary():
    client, _launcher, _opened_urls, _auditor, _registry = _client_with_seed(
        processes=[models.Process(id="game-a", name="Game A", monitoring_path="/game.exe", launch_path="/game.url")],
        sessions=[
            models.ProcessSession(
                process_id="game-a",
                process_name="Game A",
                start_timestamp=1778457600.0,
                end_timestamp=1778461200.0,
                session_duration=3600.0,
            )
        ],
        mobile_sessions=[
            models.MobileGameSession(
                id="mobile-a",
                game_link_id="link-a",
                pc_process_id="game-a",
                pc_display_name="Game A",
                android_package_name="dev.game.a",
                source="manual",
                status="ended",
                started_at=1778464800.0,
                ended_at=1778468400.0,
                duration_seconds=3600.0,
                created_at=1778464800.0,
                updated_at=1778468400.0,
            ),
            models.MobileGameSession(
                id="mobile-active",
                game_link_id="link-a",
                pc_process_id="game-a",
                pc_display_name="Game A",
                android_package_name="dev.game.a",
                source="usage_stats",
                status="active",
                started_at=1778493400.0,
                ended_at=None,
                duration_seconds=None,
                created_at=1778493400.0,
                updated_at=1778493400.0,
            ),
        ],
    )

    status_response = client.get("/remote/status")
    summary_response = client.get("/remote/dashboard/summary?start=2026-05-11&end=2026-05-11")

    assert status_response.status_code == 200
    assert status_response.json()["capabilities"]["dashboard_summary"] is True
    assert summary_response.status_code == 200
    body = summary_response.json()
    assert body["range"] == {"start": "2026-05-11", "end": "2026-05-11"}
    assert body["metrics"]["total_seconds"] == 3600.0
    assert body["metrics"]["session_count"] == 1
    assert body["metrics"]["top_game"]["display_name"] == "Game A"
    assert body["mobile_metrics"]["total_seconds"] == 7200.0
    assert body["mobile_metrics"]["active_seconds"] == 3600.0
    assert body["mobile_metrics"]["session_count"] == 2
    assert body["mobile_metrics"]["active_session_count"] == 1
    assert body["mobile_metrics"]["source_breakdown"] == {"manual": 1, "usage_stats": 1}
    assert body["mobile_metrics"]["top_game"]["display_name"] == "Game A"
    assert body["mobile_metrics"]["top_game"]["android_package_name"] == "dev.game.a"


def test_remote_capabilities_endpoint_matches_status_capability_contract():
    controller = ConfigurablePowerController(
        RemotePowerConfig(
            smartthings_device_id="device-1",
            smartthings_cli_path="/opt/homebrew/bin/smartthings",
        ),
        runner=lambda _args, _timeout: True,
        tcp_checker=lambda _host, _port, _timeout: False,
    )
    client, _launcher, _opened_urls, _auditor, _registry = _client_with_seed(
        auth_token="secret-token",
        power_controller=controller,
    )

    headers = {"Authorization": "Bearer secret-token"}
    status_response = client.get("/remote/status", headers=headers)
    capabilities_response = client.get("/remote/capabilities", headers=headers)

    assert status_response.status_code == 200
    assert capabilities_response.status_code == 200
    status_body = status_response.json()
    capabilities_body = capabilities_response.json()
    assert capabilities_body["remote_api_version"] == status_body["remote_api_version"]
    assert capabilities_body["capabilities"] == status_body["capabilities"]
    assert capabilities_body["capabilities"]["auth_required"] is True
    assert capabilities_body["capabilities"]["power_control"] is True
    assert capabilities_body["power"]["supported_actions"] == ["wake"]


def test_remote_power_config_can_be_saved_without_sending_power_commands(tmp_path):
    config_path = tmp_path / "remote_power_config.json"
    controller = ConfigurablePowerController(
        RemotePowerConfig(),
        runner=lambda _args, _timeout: (_ for _ in ()).throw(AssertionError("power command should not run")),
        tcp_checker=lambda _host, _port, _timeout: False,
    )
    client, _launcher, _opened_urls, auditor, _registry = _client_with_seed(
        power_controller=controller,
        power_config_path=config_path,
    )

    before = client.get("/remote/power/config")
    saved = client.put(
        "/remote/power/config",
        json={
            "smartthings_device_id": "device-1",
            "smartthings_cli_path": "/opt/homebrew/bin/smartthings",
            "ssh_host": "pc.example.test",
            "ssh_port": 50022,
            "ssh_user": "player",
            "ssh_key_path": "~/.ssh/id_ed25519",
            "status_timeout_seconds": 3.0,
        },
    )
    status_response = client.get("/remote/status")

    assert before.status_code == 200
    assert before.json()["config_exists"] is False
    assert saved.status_code == 200
    body = saved.json()
    assert body["config_exists"] is True
    assert body["config"]["ssh_host"] == "pc.example.test"
    assert body["readiness"]["supported_actions"] == ["wake", "shutdown", "sleep", "restart"]
    assert config_path.exists()
    assert status_response.json()["capabilities"]["power_control"] is True
    assert set(status_response.json()["power"]["supported_actions"]) == {"wake", "shutdown", "sleep", "restart"}
    assert auditor.events[-1]["command"] == "power.config.update"
    assert auditor.events[-1]["metadata"] == {"wake_configured": True, "ssh_configured": True}


def test_remote_beholder_incidents_exposes_pending_incidents_without_resolving():
    client, _launcher, _opened_urls, _auditor, _registry = _client_with_seed(
        incidents=[
            models.BeholderIncident(
                severity="warning",
                status="pending",
                operation_kind="runtime_stop",
                actor="runtime",
                target_summary="Game A session",
                suspected_cause="test",
                current_state_summary="open",
                proposed_change_summary="close",
                risk_score=7,
                risk_factors=["stale_heartbeat"],
                safe_recommendation="검토 후 처리하세요.",
                user_title="플레이 기록 확인 필요",
                created_at=1778497000.0,
            ),
            models.BeholderIncident(
                severity="info",
                status="resolved",
                operation_kind="runtime_stop",
                actor="runtime",
                target_summary="Old session",
                suspected_cause="test",
                current_state_summary="open",
                proposed_change_summary="close",
                risk_score=1,
                risk_factors=[],
                safe_recommendation="resolved",
                user_title="resolved",
                created_at=1778496000.0,
                resolved_at=1778496500.0,
            ),
        ],
    )

    response = client.get("/remote/beholder/incidents")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["incidents"][0]["user_title"] == "플레이 기록 확인 필요"
    assert body["incidents"][0]["status"] == "pending"
    assert body["incidents"][0]["risk_labels"] == ["마지막 앱 생존 시각이 너무 오래됨"]



def test_remote_game_links_create_and_list_android_package_mapping():
    client, _launcher, _opened_urls, auditor, _registry = _client_with_seed(
        processes=[models.Process(id="game-a", name="Game A", monitoring_path="/game.exe", launch_path="/game.url")],
        game_links=[
            models.GamePlatformLink(
                id="link-old",
                pc_process_id="game-a",
                pc_display_name="Game A",
                android_package_name="com.example.old",
                sync_strategy="manual",
                created_at=1778496000.0,
                updated_at=1778496000.0,
            )
        ],
    )

    listed = client.get("/remote/game-links")
    created = client.post(
        "/remote/game-links",
        json={
            "pc_process_id": "game-a",
            "android_package_name": "com.example.game",
            "android_launch_intent_uri": "intent://game#Intent;package=com.example.game;end",
            "android_store_url": "https://play.google.com/store/apps/details?id=com.example.game",
            "platform_account_hint": "same HoYoLab account",
            "hoyolab_game_id": "hkrpg",
            "sync_strategy": "usage_stats",
        },
    )
    relisted = client.get("/remote/game-links")

    assert listed.status_code == 200
    assert listed.json()["count"] == 1
    assert listed.json()["links"][0]["android_package_name"] == "com.example.old"
    assert created.status_code == 200
    body = created.json()
    assert body["pc_process_id"] == "game-a"
    assert body["pc_display_name"] == "Game A"
    assert body["android_package_name"] == "com.example.game"
    assert body["sync_strategy"] == "usage_stats"
    assert body["created_at"] == 1778497000.0
    assert relisted.json()["count"] == 2
    assert auditor.events[-1]["command"] == "game_link.create"
    assert auditor.events[-1]["target"] == "com.example.game"


def test_remote_game_link_create_rejects_unknown_pc_process():
    client, _launcher, _opened_urls, _auditor, _registry = _client_with_seed()

    response = client.post(
        "/remote/game-links",
        json={"pc_process_id": "missing", "android_package_name": "com.example.game"},
    )

    assert response.status_code == 404



def test_remote_mobile_sessions_start_end_from_game_link_and_audit():
    client, _launcher, _opened_urls, auditor, _registry = _client_with_seed(
        processes=[models.Process(id="game-a", name="Game A", monitoring_path="/game.exe", launch_path="/game.url")],
        game_links=[
            models.GamePlatformLink(
                id="link-a",
                pc_process_id="game-a",
                pc_display_name="Game A",
                android_package_name="com.example.game",
                sync_strategy="manual",
                created_at=1778496000.0,
                updated_at=1778496000.0,
            )
        ],
    )

    started = client.post("/remote/mobile-sessions/start", json={"game_link_id": "link-a", "source": "manual"})
    active = client.get("/remote/mobile-sessions/active")
    ended = client.post("/remote/mobile-sessions/end", json={"session_id": started.json()["id"], "ended_at": 1778497060.0})
    active_after_end = client.get("/remote/mobile-sessions/active")

    assert started.status_code == 200
    started_body = started.json()
    assert started_body["game_link_id"] == "link-a"
    assert started_body["pc_process_id"] == "game-a"
    assert started_body["android_package_name"] == "com.example.game"
    assert started_body["status"] == "active"
    assert active.json()["count"] == 1
    assert active.json()["sessions"][0]["id"] == started_body["id"]
    assert ended.status_code == 200
    assert ended.json()["status"] == "ended"
    assert ended.json()["duration_seconds"] == 60.0
    assert active_after_end.json()["count"] == 0
    assert [event["command"] for event in auditor.events[-2:]] == ["mobile_session.start", "mobile_session.end"]


def test_remote_mobile_session_start_accepts_usage_stats_source_and_started_at():
    client, _launcher, _opened_urls, auditor, _registry = _client_with_seed(
        processes=[models.Process(id="game-a", name="Game A", monitoring_path="/game.exe", launch_path="/game.url")],
        game_links=[
            models.GamePlatformLink(
                id="link-a",
                pc_process_id="game-a",
                pc_display_name="Game A",
                android_package_name="com.example.game",
                sync_strategy="usage_stats",
                created_at=1778496000.0,
                updated_at=1778496000.0,
            )
        ],
    )

    response = client.post(
        "/remote/mobile-sessions/start",
        json={"game_link_id": "link-a", "source": "usage_stats", "started_at": 1778496900.0},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "usage_stats"
    assert body["started_at"] == 1778496900.0
    assert auditor.events[-1]["metadata"] == {"game_link_id": "link-a", "source": "usage_stats"}


def test_remote_mobile_session_start_rejects_unknown_game_link():
    client, _launcher, _opened_urls, _auditor, _registry = _client_with_seed()

    response = client.post("/remote/mobile-sessions/start", json={"game_link_id": "missing"})

    assert response.status_code == 404


def test_remote_launch_can_request_direct_mode_without_mutating_process_preference():
    client, launcher, _opened_urls, auditor, _registry = _client_with_seed(
        processes=[
            models.Process(
                id="game-a",
                name="Game A",
                monitoring_path="/Applications/Game.app",
                launch_path="/Users/me/Desktop/Game.url",
                preferred_launch_type="shortcut",
            )
        ]
    )

    response = client.post("/remote/processes/game-a/launch", json={"mode": "direct"})

    assert response.status_code == 200
    body = response.json()
    assert body["command"] == "process.launch.direct"
    assert body["target"] == "/Applications/Game.app"
    assert launcher.targets == ["/Applications/Game.app"]
    assert auditor.events[-1]["metadata"] == {"mode": "direct"}


def test_remote_shortcut_open_delegates_to_native_opener_and_records_command_result():
    client, _launcher, opened_urls, auditor, _registry = _client_with_seed(
        shortcuts=[models.WebShortcut(id="web-a", name="Web A", url="https://example.com")]
    )

    response = client.post("/remote/shortcuts/web-a/open")

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert body["command"] == "shortcut.open"
    assert body["target"] == "https://example.com"
    assert opened_urls == ["https://example.com"]
    assert auditor.events[-1]["command"] == "shortcut.open"


def test_remote_power_commands_are_safely_rejected_until_adapter_is_configured():
    client, _launcher, _opened_urls, auditor, _registry = _client_with_seed()

    status_response = client.get("/remote/power/status")
    action_response = client.post("/remote/power/shutdown")

    assert status_response.status_code == 200
    assert status_response.json()["configured"] is False
    assert action_response.status_code == 200
    body = action_response.json()
    assert body["accepted"] is False
    assert body["command"] == "power.shutdown"
    assert body["status"] == "not_configured"
    assert auditor.events[-1]["command"] == "power.shutdown"
    assert auditor.events[-1]["accepted"] is False


def test_remote_api_can_require_bearer_token_for_nonlocal_exposure():
    client, _launcher, _opened_urls, _auditor, _registry = _client_with_seed(auth_token="secret-token")

    rejected = client.get("/remote/status")
    accepted = client.get("/remote/status", headers={"Authorization": "Bearer secret-token"})

    assert rejected.status_code == 401
    assert accepted.status_code == 200
    assert accepted.json()["capabilities"]["auth_required"] is True


def test_remote_api_force_auth_blocks_before_first_pairing_when_bound_externally():
    client, _launcher, _opened_urls, _auditor, _registry = _client_with_seed(require_auth=True)

    response = client.get("/remote/status")

    assert response.status_code == 401


def test_pairing_code_registers_device_token_and_revoke_blocks_it():
    client, _launcher, _opened_urls, _auditor, _registry = _client_with_seed()

    initial = client.get("/remote/status")
    start = client.post("/remote/pair/start")
    code = start.json()["code"]
    confirm = client.post(
        "/remote/pair/confirm",
        json={"code": code, "device_name": "MacBook", "platform": "macos"},
    )
    token = confirm.json()["token"]
    device_id = confirm.json()["id"]
    rejected_after_pairing = client.get("/remote/status")
    accepted_after_pairing = client.get("/remote/status", headers={"Authorization": f"Bearer {token}"})
    devices = client.get("/remote/devices", headers={"Authorization": f"Bearer {token}"})
    revoked = client.delete(f"/remote/devices/{device_id}", headers={"Authorization": f"Bearer {token}"})
    rejected_after_revoke = client.get("/remote/status", headers={"Authorization": f"Bearer {token}"})

    assert initial.status_code == 200
    assert initial.json()["capabilities"]["auth_required"] is False
    assert start.status_code == 200
    assert code.isdigit() and len(code) == 6
    assert confirm.status_code == 200
    assert confirm.json()["name"] == "MacBook"
    assert rejected_after_pairing.status_code == 401
    assert accepted_after_pairing.status_code == 200
    assert accepted_after_pairing.json()["capabilities"]["auth_required"] is True
    assert devices.status_code == 200
    assert devices.json()["devices"][0]["id"] == device_id
    assert revoked.status_code == 200
    assert rejected_after_revoke.status_code == 401


def test_device_token_refresh_rotates_bearer_token_and_audits_security_event():
    client, _launcher, _opened_urls, auditor, _registry = _client_with_seed()

    start = client.post("/remote/pair/start")
    confirm = client.post(
        "/remote/pair/confirm",
        json={"code": start.json()["code"], "device_name": "Android", "platform": "android"},
    )
    old_token = confirm.json()["token"]
    device_id = confirm.json()["id"]
    refresh = client.post("/remote/tokens/refresh", headers={"Authorization": f"Bearer {old_token}"})
    new_token = refresh.json()["token"]
    old_rejected = client.get("/remote/status", headers={"Authorization": f"Bearer {old_token}"})
    new_accepted = client.get("/remote/status", headers={"Authorization": f"Bearer {new_token}"})
    devices = client.get("/remote/devices", headers={"Authorization": f"Bearer {new_token}"})

    assert refresh.status_code == 200
    assert refresh.json()["id"] == device_id
    assert new_token and new_token != old_token
    assert old_rejected.status_code == 401
    assert new_accepted.status_code == 200
    assert devices.json()["devices"][0]["token_refreshed_at"] == 1778497000.0
    assert auditor.events[-1]["command"] == "token.refresh"
    assert auditor.events[-1]["target_id"] == device_id


def test_pairing_start_is_limited_to_loopback_or_authenticated_devices():
    client, _launcher, _opened_urls, _auditor, _registry = _client_with_seed(client_address=("203.0.113.10", 50000))

    response = client.post("/remote/pair/start")

    assert response.status_code == 403


def test_configured_power_controller_uses_pc_remote_smartthings_and_ssh_commands():
    commands: list[list[str]] = []
    config = RemotePowerConfig(
        smartthings_device_id="device-1",
        smartthings_cli_path="/opt/homebrew/bin/smartthings",
        ssh_host="pc.example.test",
        ssh_port=50022,
        ssh_user="player",
        ssh_key_path="~/.ssh/id_ed25519",
    )
    controller = ConfigurablePowerController(
        config,
        runner=lambda args, _timeout: commands.append(list(args)) is None or True,
        tcp_checker=lambda _host, _port, _timeout: True,
    )
    client, _launcher, _opened_urls, _auditor, _registry = _client_with_seed(power_controller=controller)

    remote_status_response = client.get("/remote/status")
    status_response = client.get("/remote/power/status")
    wake_response = client.post("/remote/power/wake")
    shutdown_response = client.post("/remote/power/shutdown")
    sleep_response = client.post("/remote/power/sleep")
    restart_response = client.post("/remote/power/restart")

    assert remote_status_response.status_code == 200
    remote_status_body = remote_status_response.json()
    assert remote_status_body["capabilities"]["power_control"] is True
    assert remote_status_body["power"]["configured"] is True
    assert remote_status_body["power"]["state"] == "on"
    assert remote_status_body["power"]["status"] == "on"
    assert remote_status_body["power"]["target_host"] == "pc.example.test"
    assert set(remote_status_body["power"]["supported_actions"]) == {"wake", "shutdown", "sleep", "restart"}
    assert status_response.status_code == 200
    status_body = status_response.json()
    assert status_body["configured"] is True
    assert status_body["state"] == "on"
    assert status_body["status"] == "on"
    assert status_body["target_host"] == "pc.example.test"
    assert set(status_body["supported_actions"]) == {"wake", "shutdown", "sleep", "restart"}
    assert wake_response.json()["accepted"] is True
    assert shutdown_response.json()["accepted"] is True
    assert sleep_response.json()["accepted"] is True
    assert restart_response.json()["accepted"] is True
    assert commands[0] == ["/opt/homebrew/bin/smartthings", "devices:commands", "device-1", "switch:on"]
    assert commands[1][-1] == "shutdown /s /t 0"
    assert commands[2][-1] == "rundll32.exe powrprof.dll,SetSuspendState 0,0,0"
    assert commands[3][-1] == "shutdown /r /t 0"
    assert "player@pc.example.test" in commands[1]
    assert "50022" in commands[1]
