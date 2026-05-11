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
    auth_token=None,
    device_registry=None,
    power_controller=None,
    require_auth=False,
    client_address=("testclient", 50000),
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
    assert body["remote_api_version"] == "0.1.0"
    assert body["counts"]["processes"] == 1
    assert body["counts"]["shortcuts"] == 1
    assert body["capabilities"]["process_launch"] is True
    assert body["capabilities"]["shortcut_open"] is True
    assert body["capabilities"]["power_control"] is False


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

    status_response = client.get("/remote/power/status")
    wake_response = client.post("/remote/power/wake")
    shutdown_response = client.post("/remote/power/shutdown")
    sleep_response = client.post("/remote/power/sleep")
    restart_response = client.post("/remote/power/restart")

    assert status_response.status_code == 200
    status_body = status_response.json()
    assert status_body["configured"] is True
    assert status_body["state"] == "on"
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
