#!/usr/bin/env python3
"""Smoke test an already-running Remote Agent over LAN/Tailscale/ZeroTier.

This script does not start or configure networking.  It verifies that a supplied
Remote Agent URL behaves like the native clients expect: /remote/status returns
HomeworkHelper metadata, optional bearer token auth works, and required remote
capabilities are present.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


REQUIRED_CAPABILITIES = (
    "process_launch",
    "shortcut_open",
    "power_control",
    "auth_required",
    "pairing",
)


def _json_request(method: str, base_url: str, path: str, *, token: str | None = None, timeout: float = 5.0) -> tuple[int, dict[str, Any]]:
    url = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8")
            return response.status, json.loads(payload) if payload else {}
    except HTTPError as exc:
        payload = exc.read().decode("utf-8")
        try:
            parsed = json.loads(payload) if payload else {}
        except json.JSONDecodeError:
            parsed = {"raw": payload}
        return exc.code, parsed


def _validate_status(body: dict[str, Any], *, require_auth: bool | None = None) -> None:
    if body.get("app") != "HomeworkHelper":
        raise AssertionError(f"unexpected app field: {body.get('app')!r}")
    if not body.get("remote_api_version"):
        raise AssertionError("remote_api_version missing")
    counts = body.get("counts") or {}
    for key in ["processes", "shortcuts", "active_sessions"]:
        if key not in counts:
            raise AssertionError(f"counts.{key} missing")
    capabilities = body.get("capabilities") or {}
    for key in REQUIRED_CAPABILITIES:
        if key not in capabilities:
            raise AssertionError(f"capabilities.{key} missing")
    if require_auth is not None and capabilities.get("auth_required") is not require_auth:
        raise AssertionError(f"auth_required expected {require_auth}, got {capabilities.get('auth_required')}")
    power = body.get("power") or {}
    for key in ["configured", "supported_actions"]:
        if key not in power:
            raise AssertionError(f"power.{key} missing")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke test LAN/Tailscale/ZeroTier Remote Agent connectivity.")
    parser.add_argument("--base-url", required=True, help="Remote Agent base URL, e.g. http://100.x.y.z:8000")
    parser.add_argument("--token", default=None, help="Bearer token for an already paired device.")
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--expect-auth", action="store_true", help="Assert /remote/status requires/advertises auth_required=true.")
    parser.add_argument("--expect-no-auth", action="store_true", help="Assert /remote/status advertises auth_required=false.")
    args = parser.parse_args(argv)

    if args.expect_auth and args.expect_no_auth:
        print("Choose only one of --expect-auth or --expect-no-auth.", file=sys.stderr)
        return 1

    try:
        unauth_status, unauth_body = _json_request("GET", args.base_url, "/remote/status", timeout=args.timeout)
        if args.expect_auth and not args.token:
            if unauth_status != 401:
                raise AssertionError(f"expected unauthenticated /remote/status to return 401, got {unauth_status}: {unauth_body}")
            print("Unauthenticated /remote/status correctly returned 401.")
        elif unauth_status == 200:
            _validate_status(unauth_body, require_auth=False if args.expect_no_auth else None)
            print(f"Unauthenticated /remote/status passed: api={unauth_body.get('remote_api_version')}")
        elif unauth_status == 401 and not args.token:
            print("Remote Agent requires auth; provide --token to verify authenticated connectivity.", file=sys.stderr)
            return 2
        elif unauth_status not in {200, 401}:
            raise AssertionError(f"unexpected /remote/status response {unauth_status}: {unauth_body}")

        if args.token:
            authed_status, authed_body = _json_request("GET", args.base_url, "/remote/status", token=args.token, timeout=args.timeout)
            if authed_status != 200:
                raise AssertionError(f"authenticated /remote/status failed {authed_status}: {authed_body}")
            _validate_status(authed_body, require_auth=True if args.expect_auth else None)
            print(f"Authenticated /remote/status passed: api={authed_body.get('remote_api_version')}")

        print(f"Remote Controller connectivity smoke passed: {args.base_url}")
        return 0
    except (AssertionError, URLError, TimeoutError, OSError) as exc:
        print(f"Remote Controller connectivity smoke failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
