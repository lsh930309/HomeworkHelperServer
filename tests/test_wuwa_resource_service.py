"""명조 제공자의 계정 선택·실제 관측 시작·제한된 재시도 계약을 검증한다."""
from __future__ import annotations

import datetime as dt
import json
from types import SimpleNamespace

import pytest


pytestmark = pytest.mark.usefixtures("wuwa_config_memory")
TOKEN = "qa_wuwa_service_token_never_output"
ROLE_ID = "799900001"
RESOURCE_KEY = "waveplate"
ACCOUNT_KEY = f"waveplate@Asia@{ROLE_ID}"
VALUES = {"Energy": 120, "MaxEnergy": 240, "StoreEnergy": 80, "MaxStoreEnergy": 480}
NOW = dt.datetime(2026, 11, 17, 10, tzinfo=dt.timezone.utc).timestamp()


def test_shared_isolation_blocks_both_real_gateway_entry_points_before_default_use():
    from src.services.wuwa import WuwaGateway
    gateway = WuwaGateway()
    with pytest.raises(AssertionError, match="실제 인증"):
        gateway.read_accounts()
    with pytest.raises(AssertionError, match="실제 인증"):
        gateway.post_json("queryRole", {}, 1.0)


@pytest.fixture
def provider(wuwa_config_memory):
    from src.services.wuwa import WuwaService

    state = SimpleNamespace(
        now=NOW, mono=1000.0, accounts=[TOKEN], calls=[], sleeps=[], sequence=[],
        role_id=ROLE_ID, role_codes=[], role_http=200, info_http=200, info_code=0,
        resource_values=dict(VALUES), on_role=None,
    )

    class Gateway:
        def read_accounts(self):
            return list(state.accounts)

        def post_json(self, operation, payload, timeout):
            state.calls.append((operation, dict(payload), timeout))
            state.sequence.append(operation)
            if operation == "queryPlayerInfo":
                return state.info_http, {"code": state.info_code, "message": TOKEN, "data": {
                    "Asia": json.dumps({"roleId": state.role_id, "name": "격리 계정"}),
                }}
            assert operation == "queryRole"
            if state.on_role:
                state.on_role()
            code = state.role_codes.pop(0) if state.role_codes else 200
            return state.role_http, {"code": code, "message": TOKEN, "data": {"Asia": json.dumps({
                "Base": {**state.resource_values, "EnergyRecoverTime": 123456789,
                         "StoreEnergyRecoverTime": 987654321, "Name": "격리 계정"},
            })}}

    def sleep(seconds):
        state.sleeps.append(seconds)
        state.now += seconds
        state.mono += seconds

    state.service = WuwaService(gateway=Gateway(), sleep=sleep, clock=lambda: state.now,
                                monotonic=lambda: state.mono)
    return state


def test_wuwa_discovery_returns_role_identity_without_auth_value(provider):
    discovery = provider.service.discover_accounts()
    assert discovery.status == "ok"
    assert [account.resource_key for account in discovery.accounts] == [ACCOUNT_KEY]
    assert TOKEN not in repr(discovery)
    assert all(call[0] == "queryPlayerInfo" for call in provider.calls)


def test_wuwa_snapshot_keeps_four_quantities_and_uses_host_observation_time(provider):
    snapshot = provider.service.get_resource_snapshot(RESOURCE_KEY)
    assert snapshot.status == "ok"
    assert (snapshot.current, snapshot.maximum, snapshot.reserve_current, snapshot.reserve_max) == (120, 240, 80, 480)
    assert snapshot.percent == 50.0
    assert snapshot.updated_at.timestamp() == NOW
    assert TOKEN not in str(snapshot)
    assert provider.sleeps == []


def test_wuwa_1005_retries_only_after_half_second_and_checks_each_resource_start(provider):
    provider.role_codes = [1005, 200]
    def before_fetch():
        provider.sequence.append("before_fetch")
    snapshot = provider.service.get_resource_snapshot(RESOURCE_KEY, before_fetch=before_fetch)
    assert snapshot.status == "ok"
    assert provider.sleeps == [0.5]
    assert provider.sequence == ["queryPlayerInfo", "before_fetch", "queryRole", "before_fetch", "queryRole"]


def test_wuwa_repeated_1005_stops_at_five_attempts(provider):
    provider.role_codes = [1005] * 20
    snapshot = provider.service.get_resource_snapshot(RESOURCE_KEY)
    assert snapshot.status != "ok"
    assert len([call for call in provider.calls if call[0] == "queryRole"]) == 5
    assert provider.sleeps == [0.5] * 4
    assert TOKEN not in snapshot.message


@pytest.mark.parametrize("http_status,code", [(401, 200), (200, 1001), (200, 17)])
def test_wuwa_non_1005_failure_is_not_retried(provider, http_status, code):
    provider.role_http = http_status
    provider.role_codes = [code]
    snapshot = provider.service.get_resource_snapshot(RESOURCE_KEY)
    assert snapshot.status != "ok"
    assert len([call for call in provider.calls if call[0] == "queryRole"]) == 1
    assert provider.sleeps == []
    assert TOKEN not in snapshot.message


def test_wuwa_cancel_during_retry_wait_never_starts_second_resource_request(provider):
    provider.role_codes = [1005, 200]
    starts = []
    def before_fetch():
        starts.append(provider.now)
        if len(starts) > 1:
            raise RuntimeError("격리 관측 취소")
    with pytest.raises(RuntimeError, match="격리 관측 취소"):
        provider.service.get_resource_snapshot(RESOURCE_KEY, before_fetch=before_fetch)
    assert len([call for call in provider.calls if call[0] == "queryRole"]) == 1
    assert starts == [NOW, NOW + 0.5]


def test_wuwa_wrong_region_key_never_performs_http(provider):
    snapshot = provider.service.get_resource_snapshot(f"waveplate@China@{ROLE_ID}")
    assert snapshot.status != "ok"
    assert provider.calls == []


def test_wuwa_no_launcher_accounts_has_no_http_or_resource_values(provider):
    provider.accounts = []
    discovery = provider.service.discover_accounts()
    assert discovery.status != "ok" and discovery.accounts == []
    assert provider.calls == []


def test_wuwa_total_budget_prevents_http_after_slow_resource_attempt(provider):
    provider.role_codes = [1005, 200]
    provider.on_role = lambda: setattr(provider, "mono", provider.mono + 30.0)
    snapshot = provider.service.get_resource_snapshot(RESOURCE_KEY)
    assert snapshot.status != "ok"
    assert [call[0] for call in provider.calls] == ["queryPlayerInfo", "queryRole"]
    assert all(0 < call[2] <= 10.0 for call in provider.calls)


@pytest.mark.parametrize("ordinary,reserve,status", [(300, 7, "ok"), (240, 0, "ok"), (240, 481, "unavailable")])
def test_wuwa_preserves_ordinary_overcap_and_rejects_invalid_reserve(provider, ordinary, reserve, status):
    provider.resource_values.update(Energy=ordinary, StoreEnergy=reserve)
    snapshot = provider.service.get_resource_snapshot(RESOURCE_KEY)
    assert snapshot.status == status
    if status == "ok":
        assert snapshot.current == ordinary and snapshot.reserve_current == reserve
        assert snapshot.percent == 100.0


@pytest.mark.parametrize("replies,expected_status,expected_calls", [
    ([(200, 0), (500, 0)], "network_error", 2),
    ([(500, 0), (200, 0)], "network_error", 1),
    ([(200, 1001), (200, 0)], "ok", 2),
])
def test_wuwa_account_discovery_never_hides_unresolved_network_candidate(replies, expected_status, expected_calls):
    from src.services.wuwa import WuwaService
    calls = []
    class Gateway:
        def read_accounts(self):
            return [TOKEN, TOKEN + "_other"]
        def post_json(self, operation, payload, timeout):
            calls.append(payload["oauthCode"])
            status, code = replies[len(calls) - 1]
            return status, {"code": code, "message": TOKEN, "data": {"Asia": json.dumps({"roleId": ROLE_ID})}}
    result = WuwaService(gateway=Gateway()).discover_accounts()
    assert result.status == expected_status and len(calls) == expected_calls
    assert len(result.accounts) == (1 if expected_status == "ok" else 0)
    assert TOKEN not in repr(result)
