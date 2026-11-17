#!/usr/bin/env python3
"""명시적인 1회 실행으로 명조 글로벌 아시아 자원 응답만 확인한다.

기본 실행은 무접근 dry-run이다. 실제 런처 캐시·HTTPS는 LiveGateway 한 곳에서만
접근하며, 인증값·계정 식별자·원본 응답은 결과에 포함하지 않는다.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import gzip
import json
import math
import os
from pathlib import Path
import sys
import time
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


API_URLS = {
    "queryPlayerInfo": "https://pc-launcher-sdk-api.kurogame.net/game/queryPlayerInfo",
    "queryRole": "https://pc-launcher-sdk-api.kurogame.net/game/queryRole",
}
RESOURCE_FIELDS = (
    "Energy", "MaxEnergy", "EnergyRecoverTime",
    "StoreEnergy", "MaxStoreEnergy", "StoreEnergyRecoverTime",
)
ERROR_CODES = frozenset({
    "cache_missing", "cache_unreadable", "cache_invalid", "account_missing",
    "account_selection_required", "account_index_invalid", "timeout_invalid",
    "http_error", "network_error", "response_invalid", "response_too_large",
    "provider_error", "authentication_expired", "asia_role_missing",
    "role_identity_invalid", "resource_fields_missing", "resource_value_invalid",
    "probe_failed", "windows_required", "appdata_missing", "owner_required",
    "remote_input_invalid", "remote_transport_failed", "remote_response_invalid",
    "arguments_invalid",
})
MAX_CACHE_BYTES = 1024 * 1024
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class ProbeError(Exception):
    """인증값이나 I/O 예외 원문을 담지 않는 고정 실패 사유다."""

    def __init__(self, code: str):
        self.code = code if code in ERROR_CODES else "probe_failed"
        super().__init__(self.code)


def decode_oauth_code(encoded: str) -> str:
    """공식 런처 캐시 공개 구현과 같은 XOR 5 변환이다."""
    return "".join(chr(ord(character) ^ 5) for character in encoded)


def parse_cached_accounts(raw: bytes) -> list[str]:
    """계정 배열에서 인증 입력만 메모리에 남기고 개인 프로필 필드는 버린다."""
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(payload, list):
            raise ValueError
        accounts = []
        for item in payload:
            if not isinstance(item, dict):
                raise ValueError
            encoded = item.get("oauthCode")
            if not isinstance(encoded, str) or not encoded:
                raise ValueError
            decoded = decode_oauth_code(encoded)
            if not decoded or any(ord(character) < 32 for character in decoded):
                raise ValueError
            accounts.append(decoded)
        return accounts
    except (ValueError, UnicodeError, TypeError):
        raise ProbeError("cache_invalid") from None


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


class LiveGateway:
    """실제 런처 인증 파일과 고정 글로벌 HTTPS의 유일한 접근 경계다."""

    def __init__(self, appdata_root: Path):
        self._appdata_root = Path(appdata_root)

    def read_accounts(self) -> list[str]:
        root = self._appdata_root / "KR_G153"
        try:
            if not root.is_dir() or root.is_symlink():
                raise ProbeError("cache_missing")
            accounts = []
            found = False
            for folder in sorted(root.iterdir()):
                if not folder.is_dir() or folder.is_symlink():
                    continue
                cache = folder / "KRSDKUserLauncherCache.json"
                if not cache.is_file() or cache.is_symlink():
                    continue
                found = True
                with cache.open("rb") as stream:
                    raw = stream.read(MAX_CACHE_BYTES + 1)
                if len(raw) > MAX_CACHE_BYTES:
                    raise ProbeError("cache_invalid")
                accounts.extend(parse_cached_accounts(raw))
            if not found:
                raise ProbeError("cache_missing")
            return accounts
        except OSError:
            raise ProbeError("cache_unreadable") from None

    def post_json(self, operation: str, payload: dict, timeout: float) -> tuple[int, dict | None]:
        if operation not in API_URLS:
            raise ProbeError("probe_failed")
        request = Request(
            API_URLS[operation],
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        # 환경 proxy와 redirect를 통해 인증 입력이 다른 주소로 전달되지 않는다.
        opener = build_opener(ProxyHandler({}), _NoRedirect())
        try:
            with opener.open(request, timeout=timeout) as response:
                status = int(response.status)
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as error:
            status = int(error.code)
            error.close()
            return status, None
        except (OSError, ValueError):
            raise ProbeError("network_error") from None
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ProbeError("response_too_large")
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeError):
            raise ProbeError("response_invalid") from None
        if not isinstance(decoded, dict):
            raise ProbeError("response_invalid")
        return status, decoded


def _numeric(value):
    if type(value) is int:
        return value if -(2**63) <= value < 2**63 else None
    return value if type(value) is float and math.isfinite(value) else None


def _object(value) -> dict:
    return value if isinstance(value, dict) else {}


def _result() -> dict:
    return {
        "ok": False,
        "mode": "live",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": 0.0,
        "error_code": None,
        "account_count": 0,
        "selected_account_index": None,
        "http_status": {operation: None for operation in API_URLS},
        "application_code": {operation: None for operation in API_URLS},
        "resources": {field: None for field in RESOURCE_FIELDS},
        "field_present": {field: False for field in RESOURCE_FIELDS},
        "time_units": "unverified",
    }


def sanitized_result(payload: dict) -> dict:
    """호스트 응답도 허용한 수치·고정 상태만 다시 투영해 출력한다."""
    result = _result()
    result["ok"] = payload.get("ok") is True
    error = payload.get("error_code")
    result["error_code"] = error if isinstance(error, str) and error in ERROR_CODES else None
    for key in ("account_count", "selected_account_index"):
        value = payload.get(key)
        result[key] = value if type(value) is int and value >= 0 else result[key]
    elapsed = _numeric(payload.get("elapsed_seconds"))
    result["elapsed_seconds"] = elapsed if elapsed is not None and elapsed >= 0 else 0.0
    stamp = payload.get("observed_at")
    try:
        result["observed_at"] = datetime.fromisoformat(stamp).astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError, OverflowError):
        pass
    for operation in API_URLS:
        status = _object(payload.get("http_status")).get(operation)
        if type(status) is int and 100 <= status <= 599:
            result["http_status"][operation] = status
        code = _object(payload.get("application_code")).get(operation)
        result["application_code"][operation] = code if type(code) is int else None
    for field in RESOURCE_FIELDS:
        result["resources"][field] = _numeric(_object(payload.get("resources")).get(field))
        result["field_present"][field] = _object(payload.get("field_present")).get(field) is True
    if result["ok"] and (
        not all(result["field_present"].values())
        or any(value is None for value in result["resources"].values())
        or any(value != 200 for value in result["http_status"].values())
        or any(value not in (0, 200) for value in result["application_code"].values())
    ):
        result["ok"] = False
        result["error_code"] = "remote_response_invalid"
    if not result["ok"] and result["error_code"] is None:
        result["error_code"] = "remote_response_invalid"
    return result


def run_probe(gateway, *, account_index: int | None = None, timeout: float = 10.0) -> dict:
    """주입된 경계로 계정 한 개·조회 두 번만 실행하고 자원 값만 반환한다."""
    result = _result()
    started = time.monotonic()
    try:
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 1 <= timeout <= 20:
            raise ProbeError("timeout_invalid")
        accounts = gateway.read_accounts()
        result["account_count"] = len(accounts)
        if not accounts:
            raise ProbeError("account_missing")
        if account_index is None:
            if len(accounts) != 1:
                raise ProbeError("account_selection_required")
            account_index = 1
        if type(account_index) is not int or not 1 <= account_index <= len(accounts):
            raise ProbeError("account_index_invalid")
        result["selected_account_index"] = account_index
        oauth_code = accounts[account_index - 1]

        def query(operation, body):
            status, reply = gateway.post_json(operation, body, timeout)
            result["http_status"][operation] = status if type(status) is int else None
            if status != 200:
                raise ProbeError("http_error")
            if not isinstance(reply, dict):
                raise ProbeError("response_invalid")
            code = reply.get("code")
            result["application_code"][operation] = code if type(code) is int else None
            if code == 1001:
                raise ProbeError("authentication_expired")
            if type(code) is not int or code not in (0, 200):
                raise ProbeError("provider_error")
            data = reply.get("data")
            if not isinstance(data, dict):
                raise ProbeError("response_invalid")
            asia = data.get("Asia")
            if not isinstance(asia, str):
                raise ProbeError("asia_role_missing")
            try:
                parsed = json.loads(asia)
            except ValueError:
                raise ProbeError("response_invalid") from None
            if not isinstance(parsed, dict):
                raise ProbeError("response_invalid")
            return parsed

        player = query("queryPlayerInfo", {"oauthCode": oauth_code})
        player_id = player.get("roleId")
        if type(player_id) is int:
            player_id = str(player_id)
        if not isinstance(player_id, str) or not player_id.isascii() or not player_id.isdigit() or not player_id.startswith("7"):
            raise ProbeError("role_identity_invalid")
        role = query("queryRole", {"oauthCode": oauth_code, "playerId": player_id, "region": "Asia"})
        base = role.get("Base")
        if not isinstance(base, dict):
            raise ProbeError("response_invalid")
        for field in RESOURCE_FIELDS:
            result["field_present"][field] = field in base
            result["resources"][field] = _numeric(base.get(field))
        if not all(result["field_present"].values()):
            raise ProbeError("resource_fields_missing")
        if any(value is None for value in result["resources"].values()):
            raise ProbeError("resource_value_invalid")
        result["ok"] = True
    except ProbeError as error:
        result["error_code"] = error.code
    except Exception:
        result["error_code"] = "probe_failed"
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return sanitized_result(result)


def _live_gateway(appdata_root: str | None) -> LiveGateway:
    if os.name != "nt":
        raise ProbeError("windows_required")
    root = appdata_root or os.environ.get("APPDATA")
    if not root:
        raise ProbeError("appdata_missing")
    return LiveGateway(Path(root))


def _read_source() -> bytes:
    return Path(__file__).read_bytes()


def remote_script(source: bytes, *, owner: str, account_index: int | None, timeout: float) -> str:
    """인증값이 없는 동일 소스를 고정 Windows checkout의 Python stdin에 전달한다."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.host_operations import WINDOWS_REPO, ps_literal

    encoded = base64.b64encode(gzip.compress(source)).decode("ascii")
    arguments = ["--live", "--timeout", str(timeout)]
    if account_index is not None:
        arguments.extend(("--account-index", str(account_index)))
    arg_json = json.dumps(arguments)
    return "\n".join((
        "$ErrorActionPreference = 'Stop'",
        "try {",
        f"  $Repo = {ps_literal(WINDOWS_REPO)}",
        f"  $Owner = {ps_literal(owner)}",
        "  if (!(Test-Path -LiteralPath (Join-Path $Repo '.git'))) { throw 'repository_missing' }",
        "  $Sid = ([Security.Principal.NTAccount]::new($env:COMPUTERNAME,$Owner)).Translate([Security.Principal.SecurityIdentifier]).Value",
        "  $Profile = (Get-ItemProperty ('HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\ProfileList\\'+$Sid)).ProfileImagePath",
        "  $AppData = Join-Path ([Environment]::ExpandEnvironmentVariables($Profile)) 'AppData\\Roaming'",
        "  $Python = Join-Path $Repo '.venv\\Scripts\\python.exe'",
        "  if (!(Test-Path -LiteralPath $Python)) { throw 'python_missing' }",
        "  $env:PYTHONDONTWRITEBYTECODE = '1'",
        "  $env:PYTHONUTF8 = '1'",
        "  $env:PYTHONIOENCODING = 'utf-8'",
        f"  $Source = 'import base64,gzip,sys;sys.argv=[\"wuwa_resource_testbench\"]+{arg_json}+[\"--appdata-root\",sys.argv[1]];exec(compile(gzip.decompress(base64.b64decode(\"{encoded}\")),\"wuwa_resource_testbench\",\"exec\"))'",
        "  $Source | & $Python - $AppData 2>$null",
        "  exit $LASTEXITCODE",
        "} catch {",
        "  [Console]::Out.WriteLine('{\"ok\":false,\"error_code\":\"remote_transport_failed\"}')",
        "  exit 1",
        "}",
    ))


def run_remote(args, *, runner=None, source_reader=None) -> dict:
    """공용 SSH 경계를 사용하고 원격 원문·전송 예외는 출력하지 않는다."""
    result = _result()
    if not args.owner:
        result["error_code"] = "owner_required"
        return result
    if args.appdata_root:
        result["error_code"] = "remote_input_invalid"
        return result
    if not math.isfinite(args.timeout) or not 1 <= args.timeout <= 20:
        result["error_code"] = "timeout_invalid"
        return result
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from tools.ssh_host_testbench import SSHConfig, run_remote_powershell
        operation = runner or run_remote_powershell
        source = (source_reader or _read_source)()
        script = remote_script(source, owner=args.owner, account_index=args.account_index, timeout=args.timeout)
        completed = operation(SSHConfig(args.host, args.user, args.ssh_port, args.identity), script,
                              timeout=math.ceil(2 * args.timeout + 15))
        payload = json.loads(completed.stdout)
        if not isinstance(payload, dict) or type(payload.get("ok")) is not bool:
            raise ProbeError("remote_response_invalid")
        if completed.returncode != 0 and payload.get("ok") is True:
            raise ProbeError("remote_response_invalid")
        return sanitized_result(payload)
    except ProbeError as error:
        result["error_code"] = error.code
    except Exception:
        result["error_code"] = "remote_transport_failed"
    return result


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse의 원래 메시지는 사용자가 전달한 경로·입력을 되풀이할 수 있다.
        self.exit(2, '{"ok":false,"error_code":"arguments_invalid"}\n')


def main(argv=None, *, gateway_factory=None, remote_runner=None, source_reader=None) -> int:
    parser = _ArgumentParser(description="명조 글로벌 아시아 자원 읽기 1회 테스트벤치")
    parser.add_argument("--live", action="store_true", help="명시한 경우에만 실제 캐시·API 또는 SSH에 접근")
    parser.add_argument("--host", help="기존 SSH/Tailscale 대상 호스트")
    parser.add_argument("--user", help="기존 SSH 사용자")
    parser.add_argument("--owner", help="원격 런처 캐시를 소유한 Windows 사용자")
    parser.add_argument("--identity", help="기존 SSH 개인키 경로")
    parser.add_argument("--ssh-port", type=int, default=22)
    parser.add_argument("--appdata-root", help="Windows 로컬 실행의 Roaming AppData 경로")
    parser.add_argument("--account-index", type=int, help="여러 캐시 계정 중 1부터 시작하는 선택 번호")
    parser.add_argument("--timeout", type=float, default=10.0, help="각 HTTPS 조회 제한 초(1~20)")
    args = parser.parse_args(argv)
    if not args.live:
        print(json.dumps({"ok": True, "mode": "dry_run", "live_access": False}))
        return 0
    if args.host:
        result = run_remote(args, runner=remote_runner, source_reader=source_reader)
    else:
        try:
            gateway = (gateway_factory or _live_gateway)(args.appdata_root)
            result = run_probe(gateway, account_index=args.account_index, timeout=args.timeout)
        except ProbeError as error:
            result = _result()
            result["error_code"] = error.code
        except Exception:
            result = _result()
            result["error_code"] = "probe_failed"
    print(json.dumps(sanitized_result(result), ensure_ascii=False, allow_nan=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
