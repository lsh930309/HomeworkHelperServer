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
IMAGE_HITS: list[str] = []
SSH_KEYS: list[str] = []


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
                    "capabilities": {"process_launch": True, "auth_required": False},
                    "power": {
                        "configured": False,
                        "state": "client_managed",
                        "status": "client_managed",
                        "target_host": "",
                        "supported_actions": [],
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
                    "power_readiness": {
                        "state": "warning",
                        "color": "yellow",
                        "message": "Android direct power adapter 미구현",
                        "supported_actions": [],
                    },
                }
            )
            return
        if path == "/remote/processes":
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
                        "is_running": False,
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
                        "is_running": True,
                        "played_today": True,
                    },
                ]
            )
            return
        if path == "/remote/power/status":
            self._json(
                {
                    "configured": False,
                    "state": "client_managed",
                    "status": "client_managed",
                    "target_host": "",
                    "supported_actions": [],
                    "message": "Android direct power adapter 미구현",
                }
            )
            return
        if path == "/remote/power/setup":
            self._json(
                {
                    "host_platform": "windows",
                    "user": "fake-user",
                    "authorized_keys_path": "C:/Users/fake/.ssh/authorized_keys",
                    "effective_authorized_keys_path": "C:/Users/fake/.ssh/authorized_keys",
                    "ssh_service": {"available": True, "running": True, "start_type": "auto", "message": "Fake OpenSSH ready"},
                    "firewall": {"available": True, "enabled": True, "message": "Fake firewall ready"},
                    "message": "Fake power setup read-only ready",
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
            self._json(
                {
                    "accepted": True,
                    "command": "process.launch.shortcut",
                    "target_id": "fake-game-a",
                    "target_name": "Fake Game A",
                    "target": "fake://game-a",
                    "status": "accepted",
                    "message": "Fake Game A 실행 요청을 접수했습니다.",
                }
            )
            return
        if self.path == "/remote/pair/confirm":
            self._json({"id": "android-device", "name": "Android Device", "token": "fake-token"})
            return
        if self.path == "/remote/power/ssh-key":
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length).decode("utf-8", "replace") if length else "{}"
            SSH_KEYS.append(body)
            self._json({"registered": True, "already_present": False, "message": "Fake SSH public key registered"})
            return
        if self.path == "/remote/tailscale/ensure":
            self._json({
                "ready": True,
                "method": "fake",
                "message": "Fake Tailscale ready",
                "suggested_base_urls": ["http://127.0.0.1:18080"],
            })
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
