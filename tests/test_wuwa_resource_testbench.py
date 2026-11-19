"""명조 진단의 고정 읽기 범위와 인증·개인 데이터 비노출 계약을 검증한다."""
from __future__ import annotations

import builtins
import importlib
import json
import os
from pathlib import Path
import socket
import subprocess
from types import SimpleNamespace
from urllib.error import URLError
import urllib.request

import pytest


TOKEN = "qa_oauth_canary_never_output"
OTHER_TOKEN = "qa_other_oauth_canary_never_output"
PLAYER_ID = "799900001"
NICKNAME = "qa_nickname_canary_never_output"
PRIVATE_MESSAGE = "qa_remote_or_exception_canary_never_output"
RESOURCE_VALUES = {
    "Energy": 123,
    "MaxEnergy": 240,
    "EnergyRecoverTime": 1_800_000_000_000,
    "StoreEnergy": 57,
    "MaxStoreEnergy": 480,
    "StoreEnergyRecoverTime": 1_800_000_600_000,
}


def assert_private_absent(value):
    text = json.dumps(value, ensure_ascii=False, default=str)
    for private in (TOKEN, OTHER_TOKEN, PLAYER_ID, NICKNAME, PRIVATE_MESSAGE):
        assert private not in text


@pytest.fixture(autouse=True)
def deny_actual_io(monkeypatch, tmp_path):
    """모듈 import보다 먼저 실제 인증 파일·외부 연결·원격 프로세스를 차단한다."""
    process_appdata = os.environ.get("HH_TEST_APPDATA_DIR")
    assert process_appdata, "pytest 시작 전 HH_TEST_APPDATA_DIR를 임시 경로로 지정해야 한다"
    assert os.environ.get("APPDATA"), "pytest 시작 전 APPDATA를 임시 경로로 지정해야 한다"

    def blocked(*args, **kwargs):
        raise AssertionError("명조 QA에서 실제 자격·네트워크·원격 실행을 차단했습니다")

    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(urllib.request, "urlopen", blocked)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", blocked)
    monkeypatch.setattr(subprocess, "run", blocked)
    monkeypatch.setattr(subprocess, "Popen", blocked)

    original_open = builtins.open
    original_path_open = Path.open

    def check_cache_path(path):
        try:
            candidate = Path(path)
        except TypeError:
            return
        if candidate.name.casefold() == "krsdkuserlaunchercache.json":
            assert candidate.resolve().is_relative_to(tmp_path.resolve()), "실제 런처 인증 파일 접근 금지"

    def guarded_open(path, *args, **kwargs):
        check_cache_path(path)
        return original_open(path, *args, **kwargs)

    def guarded_path_open(path, *args, **kwargs):
        check_cache_path(path)
        return original_path_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(Path, "open", guarded_path_open)
    return blocked


@pytest.fixture
def bench(monkeypatch, deny_actual_io):
    api = importlib.import_module("tools.wuwa_resource_testbench")
    real_read = api.LiveGateway.read_accounts
    real_post = api.LiveGateway.post_json
    monkeypatch.setattr(api.LiveGateway, "read_accounts", deny_actual_io)
    monkeypatch.setattr(api.LiveGateway, "post_json", deny_actual_io)
    monkeypatch.setattr(api, "_live_gateway", deny_actual_io)
    monkeypatch.setattr(api, "_read_source", deny_actual_io)
    monkeypatch.setattr(api, "build_opener", deny_actual_io)
    from tools import ssh_host_testbench
    monkeypatch.setattr(ssh_host_testbench, "run_remote_powershell", deny_actual_io)
    return SimpleNamespace(api=api, real_read=real_read, real_post=real_post)


class FakeGateway:
    def __init__(self, player_info, role, *, accounts=None):
        self.accounts = [TOKEN] if accounts is None else accounts
        self.player_info = player_info
        self.role = role
        self.calls = []
        self.read_count = 0

    def read_accounts(self):
        self.read_count += 1
        return list(self.accounts)

    def post_json(self, operation, payload, timeout):
        self.calls.append((operation, payload, timeout))
        answer = self.player_info if operation == "queryPlayerInfo" else self.role
        if isinstance(answer, BaseException):
            raise answer
        return answer


def player_reply(*, region="Asia", player_id=PLAYER_ID):
    return 200, {"code": 0, "message": TOKEN, "data": {
        region: json.dumps({"roleId": player_id, "name": NICKNAME, "oauthCode": TOKEN}),
    }}


def role_reply(values=None):
    return 200, {"code": 200, "message": PRIVATE_MESSAGE, "data": {"Asia": json.dumps({
        "Base": dict(RESOURCE_VALUES if values is None else values),
        "Name": NICKNAME, "Id": PLAYER_ID, "oauthCode": TOKEN,
    })}}


def good_gateway(**kwargs):
    return FakeGateway(player_reply(), role_reply(), **kwargs)


def remote_result(**updates):
    result = {
        "ok": True, "mode": "live", "error_code": None,
        "observed_at": "2026-11-17T00:00:00+00:00", "elapsed_seconds": 0.3,
        "account_count": 1, "selected_account_index": 1,
        "http_status": {"queryPlayerInfo": 200, "queryRole": 200},
        "application_code": {"queryPlayerInfo": 0, "queryRole": 200},
        "resources": dict(RESOURCE_VALUES),
        "field_present": {field: True for field in RESOURCE_VALUES},
        "time_units": "unverified",
    }
    result.update(updates)
    return result


def test_probe_reads_only_asia_and_outputs_exact_resource_values(bench):
    gateway = good_gateway()
    result = bench.api.run_probe(gateway)
    assert result["ok"] is True
    assert result["resources"] == RESOURCE_VALUES
    assert all(result["field_present"].values())
    assert result["http_status"] == {"queryPlayerInfo": 200, "queryRole": 200}
    assert result["application_code"] == {"queryPlayerInfo": 0, "queryRole": 200}
    assert result["time_units"] == "unverified"
    assert gateway.calls == [
        ("queryPlayerInfo", {"oauthCode": TOKEN}, 10.0),
        ("queryRole", {"oauthCode": TOKEN, "playerId": PLAYER_ID, "region": "Asia"}, 10.0),
    ]
    assert_private_absent(result)


@pytest.mark.parametrize("arguments", [[], ["--host", "qa.invalid", "--owner", PRIVATE_MESSAGE]])
def test_default_and_host_without_live_never_access_io(bench, deny_actual_io, capsys, arguments):
    assert bench.api.main(arguments, gateway_factory=deny_actual_io,
                          remote_runner=deny_actual_io, source_reader=deny_actual_io) == 0
    output = capsys.readouterr()
    assert json.loads(output.out) == {"ok": True, "mode": "dry_run", "live_access": False}
    assert output.err == ""
    assert_private_absent(output.out)


def test_live_cli_reports_only_resource_result(bench, capsys):
    gateway = good_gateway()
    assert bench.api.main(["--live"], gateway_factory=lambda _: gateway) == 0
    output = capsys.readouterr()
    result = json.loads(output.out)
    assert result["resources"] == RESOURCE_VALUES and result["ok"]
    assert output.err == ""
    assert_private_absent(output.out)


@pytest.mark.parametrize("accounts,index,expected", [
    ([], None, "account_missing"),
    ([TOKEN, OTHER_TOKEN], None, "account_selection_required"),
    ([TOKEN], 0, "account_index_invalid"),
    ([TOKEN], 2, "account_index_invalid"),
    ([TOKEN], True, "account_index_invalid"),
])
def test_missing_or_ambiguous_account_never_starts_http(bench, accounts, index, expected):
    gateway = good_gateway(accounts=accounts)
    result = bench.api.run_probe(gateway, account_index=index)
    assert not result["ok"] and result["error_code"] == expected
    assert gateway.calls == []
    assert_private_absent(result)


def test_explicit_account_index_selects_only_one_auth_input(bench):
    gateway = good_gateway(accounts=[OTHER_TOKEN, TOKEN])
    result = bench.api.run_probe(gateway, account_index=2)
    assert result["ok"] and result["selected_account_index"] == 2
    assert [call[1]["oauthCode"] for call in gateway.calls] == [TOKEN, TOKEN]
    assert_private_absent(result)


@pytest.mark.parametrize("timeout", [0, 21, float("nan"), float("inf"), True, "10"])
def test_invalid_timeout_never_reads_auth_or_http(bench, timeout):
    gateway = good_gateway()
    result = bench.api.run_probe(gateway, timeout=timeout)
    assert not result["ok"] and result["error_code"] == "timeout_invalid"
    assert gateway.read_count == 0 and gateway.calls == []


@pytest.mark.parametrize("reply,expected", [
    ((401, {"message": TOKEN}), "http_error"),
    ((200, None), "response_invalid"),
    ((200, {"code": 1001, "message": TOKEN}), "authentication_expired"),
    ((200, {"code": TOKEN, "data": {}}), "provider_error"),
    ((TOKEN, {"code": 0, "message": TOKEN}), "http_error"),
    (URLError(PRIVATE_MESSAGE), "probe_failed"),
])
def test_query_failure_has_fixed_reason_and_no_retry_or_secret(bench, reply, expected):
    gateway = FakeGateway(reply, role_reply())
    result = bench.api.run_probe(gateway)
    assert not result["ok"] and result["error_code"] == expected
    assert len(gateway.calls) == 1
    assert_private_absent(result)


@pytest.mark.parametrize("reply,expected", [
    (player_reply(region="China"), "asia_role_missing"),
    (player_reply(player_id="199900001"), "role_identity_invalid"),
    (player_reply(player_id="７99900001"), "role_identity_invalid"),
    (player_reply(player_id=True), "role_identity_invalid"),
    ((200, {"code": 0, "data": {"Asia": TOKEN}}), "response_invalid"),
])
def test_other_region_or_invalid_identity_never_queries_role(bench, reply, expected):
    gateway = FakeGateway(reply, role_reply())
    result = bench.api.run_probe(gateway)
    assert not result["ok"] and result["error_code"] == expected
    assert len(gateway.calls) == 1
    assert_private_absent(result)


def test_numeric_asia_identity_is_accepted_without_becoming_output(bench):
    gateway = FakeGateway(player_reply(player_id=int(PLAYER_ID)), role_reply())
    result = bench.api.run_probe(gateway)
    assert result["ok"] and gateway.calls[1][1]["playerId"] == PLAYER_ID
    assert_private_absent(result)


def test_missing_resource_is_not_success_and_preserves_field_presence(bench):
    values = dict(RESOURCE_VALUES)
    values.pop("StoreEnergy")
    result = bench.api.run_probe(FakeGateway(player_reply(), role_reply(values)))
    assert not result["ok"] and result["error_code"] == "resource_fields_missing"
    assert result["field_present"]["StoreEnergy"] is False
    assert result["resources"]["StoreEnergy"] is None
    assert result["resources"]["Energy"] == 123


@pytest.mark.parametrize("value", [TOKEN, PLAYER_ID, NICKNAME, True, float("nan"), float("inf"), 10 ** 400])
def test_resource_values_never_copy_strings_bools_nonfinite_or_unbounded_numbers(bench, value):
    values = {**RESOURCE_VALUES, "Energy": value}
    result = bench.api.run_probe(FakeGateway(player_reply(), role_reply(values)))
    assert not result["ok"] and result["error_code"] == "resource_value_invalid"
    assert result["resources"]["Energy"] is None
    assert_private_absent(result)


def test_cache_parser_decodes_auth_and_discards_unrelated_profiles(bench):
    encoded = "".join(chr(ord(character) ^ 5) for character in TOKEN)
    raw = ("\ufeff" + json.dumps([{"oauthCode": encoded, "uid": PLAYER_ID, "name": NICKNAME}])).encode()
    assert bench.api.parse_cached_accounts(raw) == [TOKEN]


@pytest.mark.parametrize("raw", [b"\xff", b"null", b"{}", b"[{}]", b'["profile"]', b'[{"oauthCode":""}]'])
def test_malformed_cache_reports_only_fixed_error(bench, raw):
    with pytest.raises(bench.api.ProbeError) as caught:
        bench.api.parse_cached_accounts(raw)
    assert str(caught.value) == "cache_invalid"
    assert_private_absent(str(caught.value))


def test_live_cache_reader_only_reads_disposable_profile_files(bench, tmp_path):
    encoded = "".join(chr(ord(character) ^ 5) for character in TOKEN)
    cache = tmp_path / "KR_G153" / "fixture-profile" / "KRSDKUserLauncherCache.json"
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps([{"oauthCode": encoded, "name": NICKNAME}]))
    assert bench.real_read(bench.api.LiveGateway(tmp_path)) == [TOKEN]


@pytest.mark.parametrize("operation", ["queryPlayerInfo", "queryRole"])
def test_live_http_boundary_uses_only_fixed_https_no_redirect_or_environment_proxy(bench, monkeypatch, tmp_path, operation):
    captured = {}

    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, amount):
            captured["read_limit"] = amount
            return b'{"code":0}'

    class Opener:
        def open(self, request, *, timeout):
            captured.update(request=request, timeout=timeout)
            return Response()

    def build_opener(*handlers):
        captured["handlers"] = handlers
        return Opener()

    monkeypatch.setattr(bench.api, "build_opener", build_opener)
    assert bench.real_post(bench.api.LiveGateway(tmp_path), operation, {"oauthCode": TOKEN}, 10) == (200, {"code": 0})
    request = captured["request"]
    assert request.full_url == f"https://pc-launcher-sdk-api.kurogame.net/game/{operation}"
    assert request.method == "POST" and TOKEN not in request.full_url
    assert captured["timeout"] == 10
    assert captured["read_limit"] == bench.api.MAX_RESPONSE_BYTES + 1
    proxy = next(handler for handler in captured["handlers"] if isinstance(handler, urllib.request.ProxyHandler))
    assert proxy.proxies == {}
    redirect = next(handler for handler in captured["handlers"] if isinstance(handler, bench.api._NoRedirect))
    assert redirect.redirect_request(request, None, 302, TOKEN, {}, "https://qa.invalid/") is None


def test_live_http_failure_does_not_copy_error_body_or_exception(bench, monkeypatch, tmp_path):
    class Opener:
        def open(self, *args, **kwargs):
            raise URLError(PRIVATE_MESSAGE)
    monkeypatch.setattr(bench.api, "build_opener", lambda *args: Opener())
    with pytest.raises(bench.api.ProbeError) as caught:
        bench.real_post(bench.api.LiveGateway(tmp_path), "queryRole", {"oauthCode": TOKEN}, 10)
    assert str(caught.value) == "network_error"


def test_remote_cli_uses_existing_transport_and_drops_remote_private_fields(bench, capsys):
    calls = []
    raw = remote_result(uid=PLAYER_ID, nickname=NICKNAME, token=TOKEN, message=PRIVATE_MESSAGE)
    def runner(config, script, *, timeout):
        calls.append((config, script, timeout))
        return SimpleNamespace(returncode=0, stdout=json.dumps(raw), stderr=TOKEN + PRIVATE_MESSAGE)
    assert bench.api.main(["--live", "--host", "qa.invalid", "--owner", "qa_owner"],
                          remote_runner=runner, source_reader=lambda: b"# disposable probe source") == 0
    output = capsys.readouterr()
    assert json.loads(output.out)["resources"] == RESOURCE_VALUES
    assert len(calls) == 1 and calls[0][2] <= 55
    assert "C:\\VSCode\\Projects\\HomeworkHelperServer" in calls[0][1]
    assert TOKEN not in calls[0][1] and PLAYER_ID not in calls[0][1]
    assert output.err == ""
    assert_private_absent(output.out)


@pytest.mark.parametrize("payload,returncode", [
    (TOKEN, 0),
    (json.dumps(TOKEN), 0),
    (json.dumps({"ok": TOKEN}), 0),
    (json.dumps({"ok": True}), 0),
    (json.dumps(remote_result(resources={"Energy": TOKEN})), 0),
    (json.dumps(remote_result(http_status=TOKEN)), 0),
    (json.dumps(remote_result(application_code={"queryRole": TOKEN})), 0),
    (json.dumps(remote_result()), 1),
])
def test_malformed_remote_output_is_not_success_and_never_echoed(bench, capsys, payload, returncode):
    def runner(*args, **kwargs):
        return SimpleNamespace(returncode=returncode, stdout=payload, stderr=TOKEN + PRIVATE_MESSAGE)
    assert bench.api.main(["--live", "--host", "qa.invalid", "--owner", "qa_owner"],
                          remote_runner=runner, source_reader=lambda: b"# fixture") == 1
    output = capsys.readouterr()
    assert json.loads(output.out)["ok"] is False
    assert output.err == ""
    assert_private_absent(output.out)


def test_remote_transport_exception_is_not_exposed(bench, capsys):
    def runner(*args, **kwargs):
        raise RuntimeError(TOKEN + PRIVATE_MESSAGE)
    assert bench.api.main(["--live", "--host", "qa.invalid", "--owner", "qa_owner"],
                          remote_runner=runner, source_reader=lambda: b"# fixture") == 1
    output = capsys.readouterr()
    assert json.loads(output.out)["error_code"] == "remote_transport_failed"
    assert output.err == ""
    assert_private_absent(output.out)


@pytest.mark.parametrize("arguments,expected", [
    (["--live", "--host", "qa.invalid"], "owner_required"),
    (["--live", "--host", "qa.invalid", "--owner", "qa_owner", "--appdata-root", "qa_path"], "remote_input_invalid"),
    (["--live", "--host", "qa.invalid", "--owner", "qa_owner", "--timeout", "21"], "timeout_invalid"),
])
def test_invalid_remote_inputs_do_not_start_transport(bench, deny_actual_io, capsys, arguments, expected):
    assert bench.api.main(arguments, remote_runner=deny_actual_io, source_reader=deny_actual_io) == 1
    assert json.loads(capsys.readouterr().out)["error_code"] == expected
