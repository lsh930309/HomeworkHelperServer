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

    assert '@app.get("/api/gui/health")' in source
    assert '"db_ready": db_ready' in source
    assert '"dashboard_static_ready": dashboard_static["ready"]' in source
