import ast
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
    assert "app.add_exception_handler(DatabaseAccessUnavailable, database_access_exception_handler)" in source
    assert '"server_time": time.time()' in source
    assert '@app.get("/api/gui/health")' in source
    assert '"db_ready": db_ready' in source
    assert '"bind_host": api_host' in source
    assert '"remote_exposed": remote_exposed' in source
    assert '"db_probe_ms": round(db_probe_ms, 2)' in source
    assert '"dashboard_static_ready": dashboard_static["ready"]' in source
    assert '"static_probe_ms": round(static_probe_ms, 2)' in source
    assert '"total_ms": round((time.perf_counter() - started_at) * 1000, 2)' in source
    assert '"release_id"' not in source[source.index('@app.get("/api/gui/ping")') : source.index("import uvicorn")]
    assert '"git_sha"' not in source[source.index('@app.get("/api/gui/ping")') : source.index("import uvicorn")]


def test_sqlite_engine_uses_short_lived_connections_for_host_stability():
    source = Path("src/data/database.py").read_text(encoding="utf-8")

    assert "from sqlalchemy.pool import NullPool" in source
    assert "poolclass=NullPool" in source
    assert '"timeout": 5' in source
    assert "pooled SQLite connection" in source


def test_api_server_lifecycle_recovers_only_identified_api_processes():
    source = Path("homework_helper.pyw").read_text(encoding="utf-8")
    start_source = source[source.index("def start_api_server()") : source.index("def run_server_main(")]
    stop_source = source[source.index("def stop_api_server(") : source.index("def ensure_process_table_schema(")]

    assert "API_GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS = 5.0" in source
    assert "def _process_looks_like_homework_api_server" in source
    assert "def _find_api_listener_pids" in source
    assert "def _terminate_existing_api_server" in source
    assert "_terminate_existing_api_server(timeout=API_GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS)" in start_source
    assert "HomeworkHelper API 서버로 확인되지 않아 종료하지 않습니다." in source
    assert "API 포트를 점유한 프로세스를 HomeworkHelper API 서버로 확인할 수 없어" in start_source
    assert "api_server_shutdown_event = multiprocessing.Event()" in start_source
    assert "daemon=False" in start_source
    assert "process.terminate()" in stop_source
    assert "process.kill()" in stop_source
    assert "_server_pid_file_path()" in stop_source
    assert "_server_metadata_file_path()" in stop_source


def _load_stop_api_server_contract():
    source = Path("homework_helper.pyw").read_text(encoding="utf-8")
    tree = ast.parse(source)
    selected_nodes = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            target_names = {target.id for target in node.targets if isinstance(target, ast.Name)}
            if target_names & {
                "API_GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS",
                "api_server_process",
                "api_server_shutdown_event",
            }:
                selected_nodes.append(node)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "stop_api_server":
            selected_nodes.append(node)
    module = ast.fix_missing_locations(ast.Module(body=selected_nodes, type_ignores=[]))
    namespace = {}
    exec(compile(module, "homework_helper.pyw", "exec"), namespace)
    return namespace


def test_stop_api_server_sets_event_and_clears_owned_child():
    namespace = _load_stop_api_server_contract()
    namespace["_server_pid_file_path"] = lambda: "server.pid"
    namespace["_server_metadata_file_path"] = lambda: "server.json"

    class FakeOs:
        @staticmethod
        def remove(_path):
            raise FileNotFoundError

    namespace["os"] = FakeOs()

    class FakeEvent:
        def __init__(self):
            self.set_count = 0

        def set(self):
            self.set_count += 1

    class FakeProcess:
        pid = 43210

        def __init__(self):
            self.alive = True
            self.join_timeouts = []
            self.terminate_count = 0
            self.kill_count = 0

        def is_alive(self):
            return self.alive

        def join(self, timeout):
            self.join_timeouts.append(timeout)
            if self.terminate_count:
                self.alive = False

        def terminate(self):
            self.terminate_count += 1

        def kill(self):
            self.kill_count += 1
            self.alive = False

    event = FakeEvent()
    process = FakeProcess()
    namespace["api_server_shutdown_event"] = event
    namespace["api_server_process"] = process

    assert namespace["stop_api_server"]() is True
    assert event.set_count == 1
    assert process.terminate_count == 1
    assert process.kill_count == 0
    assert process.join_timeouts == [5.0, 5.0]
    assert namespace["api_server_process"] is None
    assert namespace["api_server_shutdown_event"] is None
