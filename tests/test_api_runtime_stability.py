from pathlib import Path

import requests

from src.api.client import ApiClient
from src.api.runtime_config import (
    dashboard_url,
    gui_health_url,
    resolve_api_port,
    resolve_local_api_base_url,
)


def test_runtime_config_uses_dynamic_local_port(monkeypatch):
    monkeypatch.setenv("HH_API_PORT", "43210")

    assert resolve_api_port() == 43210
    assert resolve_local_api_base_url() == "http://127.0.0.1:43210"
    assert dashboard_url() == "http://127.0.0.1:43210/dashboard"
    assert gui_health_url() == "http://127.0.0.1:43210/api/gui/health"


def test_runtime_config_falls_back_to_stable_default_for_invalid_port(monkeypatch):
    monkeypatch.setenv("HH_API_PORT", "not-a-port")

    assert resolve_api_port() == 8000
    assert resolve_local_api_base_url() == "http://127.0.0.1:8000"


def test_api_client_records_initial_connection_failures(monkeypatch):
    def fail_get(*_args, **_kwargs):
        raise requests.ConnectionError("backend unavailable")

    monkeypatch.setattr(requests, "get", fail_get)

    client = ApiClient(base_url="http://127.0.0.1:65500")

    assert client.managed_processes == []
    assert client.web_shortcuts == []
    assert client.last_connection_error is not None
    assert "backend unavailable" in client.last_connection_error
    assert len(client.initial_load_errors) == 3


def test_startup_defers_api_server_start_until_primary_instance():
    source = Path("homework_helper.pyw").read_text(encoding="utf-8")
    main_tail = source[source.index('if __name__ == "__main__":') :]

    assert "def start_primary_application(instance_manager: SingleInstanceApplication):" in main_tail
    assert "main_app_start_callback=start_primary_application" in main_tail
    assert main_tail.index("def start_primary_application") < main_tail.index("run_with_single_instance_check")
    assert main_tail.index("if not start_api_server():") < main_tail.index("start_main_application(instance_manager)")


def test_gui_health_endpoint_contract_is_present():
    source = Path("homework_helper.pyw").read_text(encoding="utf-8")

    assert '@app.middleware("http")' in source
    assert "slow_api_request method=%s path=%s status=%s duration_ms=%.1f pid=%s thread=%s" in source
    assert '@app.get("/api/gui/ping")' in source
    assert '"server_time": time.time()' in source
    assert '@app.get("/api/gui/health")' in source
    assert '"db_ready": db_ready' in source
    assert '"bind_host": api_host' in source
    assert '"remote_exposed": remote_exposed' in source
    assert '"db_probe_ms": round(db_probe_ms, 2)' in source
    assert '"dashboard_static_ready": dashboard_static["ready"]' in source
    assert '"static_probe_ms": round(static_probe_ms, 2)' in source
    assert '"total_ms": round((time.perf_counter() - started_at) * 1000, 2)' in source


def test_sqlite_engine_uses_short_lived_connections_for_host_stability():
    source = Path("src/data/database.py").read_text(encoding="utf-8")

    assert "from sqlalchemy.pool import NullPool" in source
    assert "poolclass=NullPool" in source
    assert '"timeout": 5' in source
    assert "pooled SQLite connection" in source


def test_api_server_lifecycle_recovers_stale_orphan_processes():
    source = Path("homework_helper.pyw").read_text(encoding="utf-8")

    assert "def _terminate_existing_api_server" in source
    assert "def _find_api_listener_pids" in source
    assert "def _is_existing_api_server_reusable" in source
    assert "_is_existing_server_healthy() and _is_existing_api_server_reusable()" in source
    assert "orphan 서버를 재사용하지 않고 재시작합니다." in source
    assert "api_listener_pids = _find_api_listener_pids(resolve_api_port())" in source
    assert "proc.kill()" in source
    assert 'metadata_file = os.path.join(data_dir, "db_server_meta.json")' in source
    assert '"parent_create_time": _process_create_time(parent_process_id)' in source
    assert "def start_parent_watchdog" in source
    assert "parent watchdog 시작" in source
    assert "os._exit(0)" in source
    assert "shutdown_api_resources(\"uvicorn_returned\")" in source


def test_server_only_entrypoint_supports_ssh_testbench_before_gui_side_effects():
    source = Path("homework_helper.pyw").read_text(encoding="utf-8")
    main_tail = source[source.index('if __name__ == "__main__":') :]

    assert "def _wants_server_only_mode" in source
    assert '{"--server", "--testbench-server", "--run-server"}' in source
    assert "run_server_main()" in main_tail
    assert main_tail.index("multiprocessing.freeze_support()") < main_tail.index("if _wants_server_only_mode():")
    assert main_tail.index("if _wants_server_only_mode():") < main_tail.index("cleanup_old_mei_folders()")
    assert main_tail.index("if _wants_server_only_mode():") < main_tail.index("check_admin_requirement()")
    assert "get_server_mutex_name()" in source
    assert '"testbench_mode": is_testbench_mode()' in source
    assert '"testbench_session_id": get_testbench_session_id()' in source


def test_gui_parent_passes_remote_server_mode_bind_host_to_api_child():
    source = Path("homework_helper.pyw").read_text(encoding="utf-8")

    assert "def _desired_child_api_bind_host()" in source
    assert "def _is_loopback_api_host(" in source
    assert '"remote_server_mode_enabled"' in source
    assert "remote_server_mode_enabled and (not explicit_host or _is_loopback_api_host(explicit_host))" in source
    assert "loopback HH_API_HOST=" in source
    assert 'return "0.0.0.0", "remote_server_mode_enabled"' in source
    assert 'return explicit_host, "HH_API_HOST"' in source
    assert 'os.environ["HH_API_HOST"] = child_bind_host' in source
    assert "api_server_process.start()" in source
    assert source.index('os.environ["HH_API_HOST"] = child_bind_host') < source.index(
        "api_server_process.start()"
    )
    assert "if child_bind_host:" in source
    assert 'os.environ.pop("HH_API_HOST", None)' in source


def test_api_server_logs_and_records_effective_bind_host_for_diagnostics():
    source = Path("homework_helper.pyw").read_text(encoding="utf-8")

    assert "API 바인딩 설정 확인: HH_API_HOST=" in source
    assert "API 바인딩 설정 확인: remote_server_mode_enabled=" in source
    assert 'metadata["api_host"] = api_host' in source
    assert 'metadata["remote_exposed"] = api_host not in {"127.0.0.1", "localhost", "::1"}' in source


def test_remote_server_mode_blocks_legacy_routes_for_non_loopback_clients():
    source = Path("homework_helper.pyw").read_text(encoding="utf-8")

    assert "async def remote_exposure_boundary_middleware(request, call_next):" in source
    assert "remote_exposed and not _request_from_loopback(request)" in source
    assert 'path != "/remote" and not path.startswith("/remote/")' in source
    assert "Remote server mode exposes only the authenticated /remote API" in source
