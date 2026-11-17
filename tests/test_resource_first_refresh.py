"""저장한 서버 ID로 첫 관측을 수행하고 canonical 값을 양쪽 화면에 전달한다."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import threading
from types import SimpleNamespace
from typing import List
from urllib.parse import urlsplit

import pytest
import requests
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QWidget
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.client import ApiClient
from src.data import crud, models, schemas
from src.data.data_models import GlobalSettings, ManagedProcess
from src.data.database_coordination import DatabaseMaintenanceCoordinator


pytestmark = pytest.mark.usefixtures("resource_test_isolation")
KEY = "waveplate@Asia@799900001"
OTHER_KEY = "waveplate@Asia@799900002"


class Queue:
    def __init__(self): self.tasks = []
    def start(self, task): self.tasks.append(task)
    def clear(self): self.tasks.clear()
    def waitForDone(self, timeout): return True


@pytest.fixture
def flow(monkeypatch, tmp_path):
    import src.core.resource_reconcile as reconciliation
    import src.gui.main_window as main
    import src.gui.sidebar.sidebar_widget as sidebar_module
    import src.services.hoyolab as hoyolab
    import src.services.nikke as nikke
    import src.services.wuwa as wuwa
    from src.core.hoyolab_reconcile import HoYoStaminaReconcileCoordinator
    from src.gui.widgets_style import CapsuleProgressBar

    app = QApplication.instance() or QApplication([])
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    state = SimpleNamespace(fail_save=False, fail_fetch=False, http=[], provider_calls=[], role="799900001",
                            statuses=[], cells=[], dialog_data=None, dialog_ok=True)
    api = FastAPI()
    def get_db():
        with sessions() as db: yield db
    names = {"get_all_processes", "get_process_by_id", "create_new_process", "update_existing_process", "observe_process_resource"}
    tree = ast.parse(Path("homework_helper.pyw").read_text(encoding="utf-8"))
    nodes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "ResourceObservationRequest"]
    nodes += [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in names]
    assert len(nodes) == 6
    scope = dict(app=api, List=List, schemas=schemas, crud=crud, Session=Session, Depends=Depends,
                 Header=Header, HTTPException=HTTPException, BaseModel=BaseModel, get_db=get_db,
                 database_coordinator=DatabaseMaintenanceCoordinator(), SessionLocal=sessions,
                 shutdown_event=threading.Event())
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), "homework_helper.pyw", "exec"), scope)
    http = TestClient(api)

    def request(_session, method, url, **kwargs):
        parsed = urlsplit(url)
        assert parsed.hostname == "first-refresh.test", "격리 ASGI 밖 HTTP는 허용하지 않는다"
        state.http.append((method.upper(), parsed.path, kwargs.get("json")))
        response = requests.Response()
        response.url = url
        if state.fail_save and method.upper() in {"POST", "PUT"} and not parsed.path.endswith("resource-observation"):
            response.status_code, response._content = 500, b'{"detail":"fixture save failure"}'
        else:
            reply = http.request(method, parsed.path, params=kwargs.get("params"), json=kwargs.get("json"), headers=kwargs.get("headers"))
            response.status_code, response._content = reply.status_code, reply.content
        return response
    # 공용 차단 fixture가 먼저 적용되고, 이 입구만 메모리 ASGI에 제한해 개방한다.
    monkeypatch.setattr(requests.sessions.Session, "request", request)
    monkeypatch.setattr(ApiClient, "_fetch_all_web_shortcuts", lambda self: [])
    monkeypatch.setattr(ApiClient, "_fetch_global_settings", lambda self: GlobalSettings(
        run_as_admin=True, screenshot_enabled=False, recording_enabled=False, obs_watch_output_dir=False))
    client = ApiClient("http://first-refresh.test")

    class Gateway:
        def read_accounts(self): return ("fixture-memory-token",)
        def post_json(self, operation, payload, timeout):
            state.provider_calls.append(operation)
            if operation == "queryPlayerInfo":
                return 200, {"code": 0, "data": {"Asia": json.dumps({"roleId": state.role})}}
            if state.fail_fetch: return 500, {}
            return 200, {"code": 200, "data": {"Asia": json.dumps({"Base": {
                "Energy": 240, "MaxEnergy": 240, "StoreEnergy": 120, "MaxStoreEnergy": 480,
            }})}}
    monkeypatch.setattr(wuwa, "WuwaGateway", Gateway)
    monkeypatch.setattr(wuwa, "_wuwa_service", None)
    monkeypatch.setattr(hoyolab, "_service_instance", None)
    monkeypatch.setattr(nikke, "_service_instance", None)

    class Host(QWidget):
        def _get_stamina_icon_path(self, process): return None
        def _adjust_window_size_to_content(self): pass
        def _record_status_event(self, *args): state.statuses.append(args)
        def populate_process_list(self):
            # 실제 GUI 데이터 모델을 서버의 canonical DTO로 다시 채운다.
            client.managed_processes = client._fetch_all_processes()
            for cell in state.cells: cell.deleteLater()
            state.cells = [main.MainWindow._create_progress_bar_widget(self, process,
                main.calculate_process_progress(process)) for process in client.managed_processes]
            if hasattr(self, "sidebar"): self.sidebar.refresh_content()
    host = Host()
    host.data_manager = client
    host.process_monitor = SimpleNamespace(active_monitored_processes={})
    coordinators = [HoYoStaminaReconcileCoordinator(client, host.process_monitor),
                    reconciliation.NikkeResourceReconcileCoordinator(client, host.process_monitor),
                    reconciliation.WuwaResourceReconcileCoordinator(client, host.process_monitor)]
    host._hoyolab_reconcile, host._nikke_resource_reconcile, host._wuwa_resource_reconcile = coordinators
    for owner in coordinators:
        owner._pool, owner._health_pool = Queue(), Queue()
        owner.resource_updated.connect(lambda _pid: host.populate_process_list())
    monkeypatch.setattr(main.MainWindow, "INSTANCE", host)
    monkeypatch.setattr(sidebar_module.SidebarWidget, "_load_icon_async", lambda *args: None)
    monkeypatch.setattr(sidebar_module.audio_control, "get_app_volume", lambda *_args: None)
    monkeypatch.setattr(sidebar_module.audio_control, "is_muted", lambda *_args: None)
    host.sidebar = sidebar_module.SidebarWidget(client)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: state.statuses.append(args[1:]))

    class Dialog:
        def __init__(self, *args, **kwargs): pass
        def exec(self): return state.dialog_ok
        def get_data(self): return state.dialog_data
    # 연결/관리 계층은 이번 수정 범위 밖이다. 실제 저장 handler의 폼 입력만 제공한다.
    monkeypatch.setattr(main, "ProcessDialog", Dialog)
    constructor = main.ManagedProcess
    def draft(**kwargs):
        kwargs.setdefault("id", "client-draft-id")
        return constructor(**kwargs)
    monkeypatch.setattr(main, "ManagedProcess", draft)
    def form(key=KEY, enabled=True):
        state.dialog_data = dict(name="명조", monitoring_path="/fixture/wuwa.exe", launch_path="/fixture/wuwa.exe",
            server_reset_time_str="04:00", user_cycle_hours=24, mandatory_times_str=[],
            is_mandatory_time_enabled=False, resource_tracking_enabled=enabled, resource_provider="wuwa" if enabled else None,
            resource_key=key if enabled else None, resource_current=999, resource_max=999, resource_reserve_current=999,
            resource_reserve_max=999)
    def create():
        main.MainWindow.open_add_process_dialog(host)
        return client.managed_processes[-1] if client.managed_processes else None
    def edit(pid): main.MainWindow.handle_edit_action_for_row(host, pid)
    def drain():
        for owner in coordinators:
            for job in list(owner._jobs.values()): owner._start_attempt(job)
            while owner._pool.tasks: owner._pool.tasks.pop(0).run()
    def observed_requests():
        return [r for r in state.http if r[1].endswith("/resource-observation")]
    state.client, state.host, state.sessions = client, host, sessions
    state.form, state.create, state.edit, state.drain = form, create, edit, drain
    state.coordinators, state.observed_requests, state.bar_type = coordinators, observed_requests, CapsuleProgressBar
    yield state
    for owner in coordinators: owner.shutdown()
    host.sidebar.cleanup(deadline_ms=1000)
    host.sidebar.close()
    for cell in state.cells: cell.close()
    host.close()
    app.processEvents()
    http.close()
    engine.dispose()


def test_new_registration_observes_server_uuid_and_renders_canonical_values(flow):
    flow.form()
    saved = flow.create()
    assert saved.id != "client-draft-id"
    with flow.sessions() as db:
        row = db.get(models.Process, saved.id)
        assert row.resource_current is None and row.resource_reserve_current is None
    assert list(flow.coordinators[2]._jobs) == [(saved.id, None)]
    flow.drain()
    assert flow.observed_requests() == [("POST", f"/processes/{saved.id}/resource-observation", {"session_id": None})]
    with flow.sessions() as db:
        row = db.get(models.Process, saved.id)
        assert (row.resource_current, row.resource_max, row.resource_reserve_current, row.resource_reserve_max) == (240, 240, 120, 480)
        assert row.resource_percent is None
        assert db.query(models.ProcessSession).count() == 0
    fresh = flow.client.get_process_by_id(saved.id)
    assert fresh.resource_status == "ok" and fresh.resource_current == 240 and fresh.resource_percent == 100
    row = flow.host.sidebar._games_list_layout.itemAt(0).widget()
    assert row.findChild(flow.bar_type, "gameProgressBar").format() == "120/480"
    assert flow.cells[0].findChild(QLabel, "progressText").text() == "120/480"


def test_existing_unlinked_game_gets_first_canonical_observation_after_activation(flow):
    flow.form(enabled=False)
    saved = flow.create()
    assert all(not owner._jobs for owner in flow.coordinators)
    flow.form()
    flow.edit(saved.id)
    assert list(flow.coordinators[2]._jobs) == [(saved.id, None)]
    flow.drain()
    assert len(flow.observed_requests()) == 1
    assert flow.client.get_process_by_id(saved.id).resource_current == 240
    with flow.sessions() as db:
        assert db.query(models.ProcessSession).count() == 0


def test_same_target_name_edit_keeps_fresh_values_without_extra_observation(flow):
    flow.form(); saved = flow.create(); flow.drain()
    flow.form(); flow.dialog_data['name'] = '수정한 명조'
    flow.edit(saved.id); flow.drain()
    assert len(flow.observed_requests()) == 1
    fresh = flow.client.get_process_by_id(saved.id)
    assert fresh.name == '수정한 명조' and fresh.resource_reserve_current == 120


@pytest.mark.parametrize('operation', ['new', 'edit'])
def test_failed_save_does_not_queue_or_report_success(flow, operation):
    if operation == 'edit':
        flow.form(enabled=False); saved = flow.create()
        flow.statuses.clear()
    flow.fail_save = True; flow.form()
    if operation == 'new':
        assert flow.create() is None
    else:
        flow.edit(saved.id)
        assert flow.client.get_process_by_id(saved.id).resource_tracking_enabled is False
    assert all(not owner._jobs for owner in flow.coordinators)
    assert flow.observed_requests() == []
    assert not any('완료' in str(message) for message in flow.statuses)


def test_first_observation_failure_keeps_saved_target_and_manual_retry_can_fill_values(flow):
    flow.fail_fetch = True; flow.form(); saved = flow.create(); flow.drain()
    with flow.sessions() as db:
        row = db.get(models.Process, saved.id)
        assert row.resource_key == KEY and row.resource_tracking_enabled is True
        assert row.resource_current is None and row.resource_reserve_current is None
    assert len(flow.observed_requests()) == 1 and not flow.coordinators[2]._jobs
    flow.fail_fetch = False
    assert flow.coordinators[2].request_refresh(saved.id)
    flow.drain()
    assert len(flow.observed_requests()) == 2
    assert flow.client.get_process_by_id(saved.id).resource_reserve_current == 120


def test_changed_target_cancels_queued_old_identity_and_observes_new_target_once(flow):
    flow.form(); saved = flow.create()
    owner = flow.coordinators[2]
    old = owner._jobs[(saved.id, None)]
    owner._start_attempt(old)
    flow.role = '799900002'; flow.form(OTHER_KEY); flow.edit(saved.id)
    assert old.cancelled.is_set() and owner._jobs[(saved.id, None)] is not old
    flow.drain()
    assert len(flow.observed_requests()) == 1
    fresh = flow.client.get_process_by_id(saved.id)
    assert fresh.resource_key == OTHER_KEY and fresh.resource_current == 240


def test_disabling_tracking_cancels_initial_job_without_starting_another(flow):
    flow.form(); saved = flow.create()
    old = flow.coordinators[2]._jobs[(saved.id, None)]
    flow.form(enabled=False); flow.edit(saved.id); flow.drain()
    assert old.cancelled.is_set() and flow.observed_requests() == []
    assert flow.client.get_process_by_id(saved.id).resource_tracking_enabled is False


@pytest.mark.parametrize('provider,index', [('hoyolab', 0), ('nikke', 1)])
def test_existing_providers_share_saved_target_entry_without_session_authority(flow, provider, index):
    flow.form()
    if provider == 'hoyolab':
        flow.dialog_data.update(stamina_tracking_enabled=True, hoyolab_game_id='honkai_starrail',
                                resource_tracking_enabled=False, resource_provider=None, resource_key=None)
    else:
        flow.dialog_data.update(resource_provider='nikke_blablalink', resource_key='nikke_outpost_storage')
    saved = flow.create()
    assert list(flow.coordinators[index]._jobs) == [(saved.id, None)]
    assert sum(len(owner._jobs) for owner in flow.coordinators) == 1
    assert flow.observed_requests() == []
