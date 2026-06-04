#!/usr/bin/env python3
"""Small fake Remote Agent for Android UI/device smoke tests."""

from __future__ import annotations

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_ICON = PROJECT_ROOT / "assets/icons/app/app_icon.png"
GAME_ICONS = {
    "fake-game-a": PROJECT_ROOT / "assets/icons/games/honkai_starrail_stamina.png",
    "fake-game-running": PROJECT_ROOT / "assets/icons/games/zenless_zone_zero_stamina.png",
}
RESOURCE_ICONS = {
    "fake-game-a": PROJECT_ROOT / "assets/icons/games/honkai_starrail_stamina.png",
    "fake-game-running": PROJECT_ROOT / "assets/icons/games/wuwa_stamina.png",
}

LAUNCHES: list[str] = []
STOPS: list[str] = []
IMAGE_HITS: list[str] = []
POWER_ACTIONS: list[str] = []
TOKEN_REFRESHES: list[str] = []
REVOKED_DEVICES: set[str] = set()


def _process_icon_urls(process_id: str) -> dict[str, str]:
    return {
        "64": f"/api/dashboard/icons/{process_id}?size=64&format=png",
        "128": f"/api/dashboard/icons/{process_id}?size=128&format=png",
    }


def _resource_icon_urls(process_id: str) -> dict[str, str]:
    return {
        "32": f"/api/dashboard/resource-icons/{process_id}?size=32",
        "64": f"/api/dashboard/resource-icons/{process_id}?size=64",
    }


class FakeRemoteHandler(BaseHTTPRequestHandler):
    def _json(self, data: object, status: int = 200) -> None:
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _png(self, path: Path) -> None:
        if not path.exists():
            self._json({"error": "png not found"}, status=404)
            return
        payload = path.read_bytes()
        IMAGE_HITS.append(self.path)
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.command} {self.path} " + fmt % args, flush=True)

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        now = time.time()
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/remote/status":
            self._json(
                {
                    "app": "HomeworkHelper",
                    "remote_api_version": "fake-android-v3",
                    "server_time": now,
                    "state_revision": f"fake-android-v3-{len(LAUNCHES)}-{len(IMAGE_HITS)}",
                    "updated_at": now,
                    "counts": {"processes": 2, "shortcuts": 0, "active_sessions": 1 if LAUNCHES else 0},
                    "capabilities": {
                        "process_launch": True,
                        "process_stop": True,
                        "auth_required": False,
                        "power_config": True,
                        "power_control": True,
                    },
                    "power": {
                        "configured": True,
                        "state": "ready",
                        "status": "ready",
                        "target_host": "Windows Host",
                        "supported_actions": ["sleep", "restart", "shutdown"],
                        "wake_mode": "smartthings_client",
                        "ssh_required": False,
                    },
                }
            )
            return
        if path == "/remote/readiness":
            self._json(
                {
                    "remote_connectivity": {
                        "state": "ok",
                        "color": "green",
                        "message": "Fake Remote Agent device smoke online",
                    },
                    "server_mode_readiness": {
                        "state": "ok",
                        "color": "green",
                        "message": "Server mode ready",
                    },
                    "remote_access_readiness": {
                        "state": "ok",
                        "color": "green",
                        "message": "Fake public HTTPS ready",
                        "public_base_url": "https://211-216-28-65.sslip.io",
                        "router_rule": {"protocol": "TCP", "external_port": 443, "internal_port": 38443, "summary": "TCP 443 -> Windows Host:38443"},
                        "warnings": [],
                    },
                    "power_readiness": {
                        "state": "ok",
                        "color": "green",
                        "message": "Host HTTPS delegated power ready; Wake는 SmartThings",
                        "supported_actions": ["sleep", "restart", "shutdown"],
                        "wake_mode": "smartthings_client",
                        "ssh_required": False,
                    },
                }
            )
            return
        if path == "/remote/access/status":
            self._json(
                {
                    "schema_version": 1,
                    "enabled": True,
                    "mode": "manual_port_forward_public_https",
                    "state": "ready",
                    "public_ip": "211.216.28.65",
                    "public_ip_source": "fake",
                    "hostname": "211-216-28-65.sslip.io",
                    "public_base_url": "https://211-216-28-65.sslip.io",
                    "agent_base_url": "http://127.0.0.1:8000",
                    "ports": {
                        "required_count": 1,
                        "rules": [{"protocol": "TCP", "external_port": 443, "internal_port": 38443, "summary": "TCP 443 -> Windows Host:38443"}],
                        "no_udp_required": True,
                        "do_not_forward": [8000],
                    },
                    "router_rule": {"protocol": "TCP", "external_port": 443, "internal_port": 38443, "target_host": "Windows Host", "summary": "TCP 443 -> Windows Host:38443"},
                    "caddy": {
                        "strategy": "caddy_sidecar",
                        "installed": True,
                        "running": True,
                        "internal_https_port": 38443,
                        "config_path": "fake/Caddyfile",
                        "config_preview": "{\\n    https_port 38443\\n}\\n\\nhttps://211-216-28-65.sslip.io {\\n    reverse_proxy 127.0.0.1:8000\\n}\\n",
                    },
                    "warnings": [],
                    "advisories": ["공유기에서 Remote Agent 8000 포트는 공개하지 마세요."],
                    "message": "Fake public HTTPS route ready",
                }
            )
            return
        if path == "/remote/processes":
            fake_game_a_running = "fake-game-a" in LAUNCHES and "fake-game-a" not in STOPS
            fake_running_game_running = "fake-game-running" not in STOPS
            self._json(
                [
                    {
                        "id": "fake-game-a",
                        "name": "Fake Game A",
                        "status_text": "대기",
                        "progress": {
                            "kind": "cycle",
                            "percentage": 42.0,
                            "display_text": "42%",
                            "resource_icon_url": "/api/dashboard/resource-icons/fake-game-a?size=32",
                            "resource_icon_urls": _resource_icon_urls("fake-game-a"),
                        },
                        "icon_url": "/api/dashboard/icons/fake-game-a?size=128&format=png",
                        "icon_urls": _process_icon_urls("fake-game-a"),
                        "is_running": fake_game_a_running,
                        "played_today": True,
                    },
                    {
                        "id": "fake-game-running",
                        "name": "Fake Running Game",
                        "status_text": "실행 중",
                        "progress": {
                            "kind": "stamina",
                            "percentage": 75.0,
                            "display_text": "150/200",
                            "resource_icon_url": "/api/dashboard/resource-icons/fake-game-running?size=32",
                            "resource_icon_urls": _resource_icon_urls("fake-game-running"),
                        },
                        "icon_url": "/api/dashboard/icons/fake-game-running?size=128&format=png",
                        "icon_urls": _process_icon_urls("fake-game-running"),
                        "is_running": fake_running_game_running,
                        "played_today": True,
                    },
                ]
            )
            return
        if path == "/remote/power/status":
            self._json(
                {
                    "configured": True,
                    "state": "ready",
                    "status": "ready",
                    "target_host": "Windows Host",
                    "supported_actions": ["sleep", "restart", "shutdown"],
                    "wake_mode": "smartthings_client",
                    "ssh_required": False,
                    "message": "Host HTTPS 위임 전원 준비 완료; Wake는 SmartThings",
                }
            )
            return
        if path == "/remote/power/setup":
            self._json(
                {
                    "host_platform": "windows",
                    "user": "fake-user",
                    "configured": True,
                    "state": "ready",
                    "status": "ready",
                    "target_host": "Windows Host",
                    "supported_actions": ["sleep", "restart", "shutdown"],
                    "wake_mode": "smartthings_client",
                    "ssh_required": False,
                    "message": "Fake Host HTTPS delegated power ready",
                }
            )
            return
        if path == "/remote/devices":
            self._json(
                {
                    "devices": [
                        {
                            "id": "android-device",
                            "name": "Android Device",
                            "platform": "android",
                            "role": "client",
                            "tailnet_ip": "",
                            "last_source_ip": "198.51.100.20",
                            "pairing_status": "paired" if "android-device" not in REVOKED_DEVICES else "revoked",
                            "connectivity_state": "active",
                            "health_message": "Fake Android device active",
                            "can_revoke": True,
                            "revoked_at": None,
                        },
                        {
                            "id": "host:100.64.0.10",
                            "name": "HomeworkHelper Host",
                            "platform": "windows",
                            "role": "host",
                            "tailnet_ip": "",
                            "last_source_ip": "211.216.28.65",
                            "pairing_status": "host",
                            "connectivity_state": "local",
                            "health_message": "Fake host online",
                            "can_revoke": False,
                            "revoked_at": None,
                        },
                    ]
                }
            )
            return
        if path.startswith("/api/dashboard/icons/"):
            process_id = path.removeprefix("/api/dashboard/icons/")
            self._png(GAME_ICONS.get(process_id, APP_ICON))
            return
        if path.startswith("/api/dashboard/resource-icons/"):
            process_id = path.removeprefix("/api/dashboard/resource-icons/")
            self._png(RESOURCE_ICONS.get(process_id, APP_ICON))
            return
        self._json({"error": "not found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        if self.path == "/remote/processes/fake-game-a/launch":
            LAUNCHES.append("fake-game-a")
            if "fake-game-a" in STOPS:
                STOPS.remove("fake-game-a")
            self._json(
                {
                    "accepted": True,
                    "command": "process.launch.shortcut",
                    "target_id": "fake-game-a",
                    "target_name": "Fake Game A",
                    "target": "fake://game-a",
                    "status": "accepted",
                    "message": "Fake Game A 실행 요청을 접수했습니다.",
                    "command_id": "process.launch.shortcut:fake",
                    "accepted_at": time.time(),
                    "refresh_after_ms": 250,
                }
            )
            return
        if self.path in {"/remote/processes/fake-game-a/stop", "/remote/processes/fake-game-running/stop"}:
            process_id = self.path.split("/")[3]
            STOPS.append(process_id)
            self._json(
                {
                    "accepted": True,
                    "command": "process.stop.terminate",
                    "target_id": process_id,
                    "target_name": process_id,
                    "target": f"fake://{process_id}",
                    "status": "accepted",
                    "message": f"{process_id} 중단 요청을 접수했습니다.",
                    "command_id": "process.stop.terminate:fake",
                    "accepted_at": time.time(),
                    "refresh_after_ms": 250,
                }
            )
            return
        if self.path == "/remote/pair/confirm":
            self._json({"id": "android-device", "name": "Android Device", "token": "fake-token"})
            return
        if self.path == "/remote/tokens/refresh":
            TOKEN_REFRESHES.append("fake-token-refresh")
            self._json({"id": "android-device", "name": "Android Device", "token": "fake-token-refreshed"})
            return
        if self.path in {
            "/remote/power/actions/sleep",
            "/remote/power/actions/restart",
            "/remote/power/actions/shutdown",
        }:
            action = self.path.removeprefix("/remote/power/actions/").strip("/")
            if action not in {"sleep", "restart", "shutdown"}:
                self._json({"accepted": False, "command": f"power.{action}", "status": "unsupported", "message": "unsupported fake power action"}, status=400)
                return
            POWER_ACTIONS.append(action)
            self._json(
                {
                    "accepted": True,
                    "command": f"power.{action}",
                    "target_id": "host",
                    "target_name": "Windows Host",
                    "target": "host",
                    "status": "accepted",
                    "message": f"Fake Host HTTPS delegated {action} accepted.",
                    "command_id": f"power.{action}:fake",
                    "accepted_at": time.time(),
                    "refresh_after_ms": 1500,
                }
            )
            return
        self._json({"error": "not found"}, status=404)

    def do_DELETE(self) -> None:  # noqa: N802 - http.server API
        if self.path == "/remote/devices/revoked":
            removed = len(REVOKED_DEVICES)
            REVOKED_DEVICES.clear()
            self._json({"removed": removed})
            return
        if self.path.startswith("/remote/devices/") and self.path != "/remote/devices/revoked":
            device_id = self.path.removeprefix("/remote/devices/")
            REVOKED_DEVICES.add(device_id)
            self._json({"revoked": True, "device_id": device_id})
            return
        self._json({"error": "not found"}, status=404)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a fake Remote Agent for Android device smoke tests.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18080)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), FakeRemoteHandler)
    print(f"Fake Android Remote Agent listening on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
