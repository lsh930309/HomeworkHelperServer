#!/usr/bin/env python3
"""Small fake Remote Agent for Android UI/device smoke tests."""

from __future__ import annotations

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LAUNCHES: list[str] = []


class FakeRemoteHandler(BaseHTTPRequestHandler):
    def _json(self, data: object, status: int = 200) -> None:
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.command} {self.path} " + fmt % args, flush=True)

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        now = time.time()
        if self.path == "/remote/status":
            self._json(
                {
                    "app": "HomeworkHelper",
                    "remote_api_version": "fake-android-v2",
                    "server_time": now,
                    "state_revision": f"fake-android-v2-{len(LAUNCHES)}",
                    "updated_at": now,
                    "counts": {"processes": 2, "shortcuts": 0, "active_sessions": 0},
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
        if self.path == "/remote/readiness":
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
        if self.path == "/remote/processes":
            self._json(
                [
                    {
                        "id": "fake-game-a",
                        "name": "Fake Game A",
                        "status_text": "대기",
                        "progress": {"kind": "cycle", "percentage": 42.0, "display_text": "42%"},
                        "icon_url": "/api/dashboard/icons/fake-game-a?size=128&format=png",
                        "is_running": False,
                        "played_today": True,
                    },
                    {
                        "id": "fake-game-running",
                        "name": "Fake Running Game",
                        "status_text": "실행 중",
                        "progress": {"kind": "stamina", "percentage": 75.0, "display_text": "150/200"},
                        "is_running": True,
                        "played_today": True,
                    },
                ]
            )
            return
        if self.path == "/remote/power/status":
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
        if self.path == "/remote/power/setup":
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
