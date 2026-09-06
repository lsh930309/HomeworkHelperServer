import os
import ctypes
import threading
import time
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QThread, Slot
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QTextEdit

from src.gui.power_events import (
    PBT_APMRESUMEAUTOMATIC,
    WM_POWERBROADCAST,
    DesiredTimerRegistry,
    WindowsPowerEventFilter,
    WindowsPowerEventParser,
)
from src.gui.work_coordinator import GuiWorkCoordinator, WorkResult
from src.core.process_monitor import ProcessLifecycleEvent
from src.gui.sidebar.sidebar_widget import _VideoThumbnailLoadTask


def _qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def _pump_until(predicate, *, timeout: float = 2.0) -> None:
    app = _qapp()
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.002)
    assert predicate()


def test_telemetry_keeps_one_running_and_only_the_latest_pending_result() -> None:
    _qapp()
    coordinator = GuiWorkCoordinator(max_threads=1)
    started = threading.Event()
    release = threading.Event()
    calls: list[str] = []
    results: list[str] = []

    def first() -> str:
        calls.append("first")
        started.set()
        release.wait(1.0)
        return "obsolete"

    def value(name: str) -> str:
        calls.append(name)
        return name

    coordinator.result_ready.connect(lambda item: results.append(item.value))
    coordinator.submit_telemetry("process_scan", first)
    assert started.wait(1.0)
    coordinator.submit_telemetry("process_scan", value, "replaced")
    coordinator.submit_telemetry("process_scan", value, "latest")

    snapshot = coordinator.snapshot()
    assert snapshot.running_telemetry == ("process_scan",)
    assert snapshot.pending_telemetry == ("process_scan",)

    release.set()
    _pump_until(lambda: calls == ["first", "latest"] and results == ["latest"])
    assert coordinator.shutdown(deadline_seconds=0.2)


def test_lifecycle_is_fifo_per_process_and_parallel_between_processes() -> None:
    _qapp()
    coordinator = GuiWorkCoordinator(max_threads=4)
    first_started = threading.Event()
    other_started = threading.Event()
    release = threading.Event()
    calls: list[str] = []
    results: list[str] = []

    def blocked_first() -> str:
        calls.append("a-start")
        first_started.set()
        release.wait(1.0)
        calls.append("a-end")
        return "a-first"

    def immediate(name: str, marker: threading.Event | None = None) -> str:
        calls.append(name)
        if marker is not None:
            marker.set()
        return name

    coordinator.result_ready.connect(lambda item: results.append(item.value))
    coordinator.submit_lifecycle("game-a", blocked_first)
    assert first_started.wait(1.0)
    coordinator.submit_lifecycle("game-a", immediate, "a-second")
    coordinator.submit_lifecycle("game-b", immediate, "b-first", other_started)

    assert other_started.wait(1.0)
    assert "a-second" not in calls
    release.set()
    _pump_until(lambda: len(results) == 3)

    assert calls.index("a-end") < calls.index("a-second")
    assert results.index("a-first") < results.index("a-second")
    assert coordinator.shutdown(deadline_seconds=0.2)


def test_completion_is_delivered_on_gui_thread_and_late_result_is_discarded() -> None:
    app = _qapp()
    coordinator = GuiWorkCoordinator(max_threads=1)

    class Receiver(QObject):
        def __init__(self) -> None:
            super().__init__()
            self.threads: list[QThread] = []

        @Slot(object)
        def receive(self, _result: WorkResult) -> None:
            self.threads.append(QThread.currentThread())

    receiver = Receiver()
    coordinator.result_ready.connect(receiver.receive)
    coordinator.submit_telemetry("heartbeat", lambda: "ok")
    _pump_until(lambda: bool(receiver.threads))
    assert receiver.threads == [app.thread()]

    started = threading.Event()
    release = threading.Event()

    def blocked() -> str:
        started.set()
        release.wait(1.0)
        return "late"

    coordinator.submit_telemetry("readiness", blocked)
    assert started.wait(1.0)
    before = len(receiver.threads)
    started_at = time.monotonic()
    assert coordinator.shutdown(deadline_seconds=0.02) is False
    assert time.monotonic() - started_at < 0.2
    release.set()
    time.sleep(0.03)
    app.processEvents()
    assert len(receiver.threads) == before


def test_power_resume_parser_debounces_and_filter_never_consumes_event() -> None:
    ticks = iter((100.0, 102.0, 106.0))
    parser = WindowsPowerEventParser(clock=lambda: next(ticks))
    assert parser.parse(WM_POWERBROADCAST, PBT_APMRESUMEAUTOMATIC) is not None
    assert parser.parse(WM_POWERBROADCAST, PBT_APMRESUMEAUTOMATIC) is None
    assert parser.parse(WM_POWERBROADCAST, PBT_APMRESUMEAUTOMATIC) is not None
    assert parser.parse(0, PBT_APMRESUMEAUTOMATIC) is None

    events = []
    event_filter = WindowsPowerEventFilter(
        events.append,
        parser=WindowsPowerEventParser(clock=lambda: 200.0),
        decoder=lambda _message: (WM_POWERBROADCAST, PBT_APMRESUMEAUTOMATIC),
    )
    assert event_filter.nativeEventFilter(b"windows_generic_MSG", object()) == (False, 0)
    assert len(events) == 1


def test_desired_timer_registry_does_not_restart_suspended_or_shutdown_timer() -> None:
    class Timer:
        def __init__(self) -> None:
            self.active = True
            self.starts: list[int] = []
            self.stops = 0

        def start(self, msec: int) -> None:
            self.active = True
            self.starts.append(msec)

        def stop(self) -> None:
            self.active = False
            self.stops += 1

        def isActive(self) -> bool:
            return self.active

    active = Timer()
    suspended = Timer()
    registry = DesiredTimerRegistry()
    registry.register("active", active, interval_ms=1000)
    registry.register("suspended", suspended, interval_ms=2000)
    registry.suspend("database_restore", ("suspended",))
    registry.restart_desired()

    assert active.starts == [1000]
    assert suspended.starts == []
    assert not suspended.active

    registry.shutdown()
    registry.restart_desired()
    assert active.starts == [1000]
    assert not active.active


def _lifecycle_command():
    from src.gui.main_window import _LifecycleCommand

    event = ProcessLifecycleEvent(
        process_id="game-a",
        process_name="Game A",
        session_id=None,
        timestamp=100.0,
        stamina_tracking_enabled=False,
        hoyolab_game_id=None,
        pid=321,
    )
    return _LifecycleCommand("start", event, 321, 100.0, "instance:game-a:321:100.000000")


def test_lifecycle_persistence_uses_exact_backoff_sequence_then_succeeds() -> None:
    from src.gui.main_window import MainWindow

    class ShutdownEvent:
        def __init__(self) -> None:
            self.delays: list[float] = []

        def is_set(self) -> bool:
            return False

        def wait(self, delay: float) -> bool:
            self.delays.append(delay)
            return False

    class Transport:
        def __init__(self) -> None:
            self.attempts = 0

        def start_session(self, **_kwargs):
            self.attempts += 1
            if self.attempts <= 5:
                raise ConnectionError("temporary")
            return {"id": 77}

    shutdown = ShutdownEvent()
    transport = Transport()
    window = SimpleNamespace(
        _background_transport=transport,
        _app_instance_id="instance",
        _lifecycle_shutdown_event=shutdown,
        _lifecycle_session_lock=threading.Lock(),
        _lifecycle_session_ids={},
    )

    result = MainWindow._persist_lifecycle_command(window, _lifecycle_command())

    assert result.succeeded is True
    assert result.session_id == 77
    assert result.attempts == 6
    assert shutdown.delays == [1.0, 2.0, 5.0, 10.0, 30.0]


def test_exhausted_lifecycle_persistence_records_one_failure_for_token() -> None:
    from src.gui.main_window import MainWindow

    class ShutdownEvent:
        def is_set(self) -> bool:
            return False

        def wait(self, _delay: float) -> bool:
            return False

    class Transport:
        def __init__(self) -> None:
            self.failure_payloads = []

        def start_session(self, **_kwargs):
            raise ConnectionError("offline")

        def post_json(self, path, payload, **_kwargs):
            assert path == "/api/beholder/runtime/lifecycle-failure"
            self.failure_payloads.append(payload)
            return SimpleNamespace(payload={"ok": True})

    transport = Transport()
    window = SimpleNamespace(
        _background_transport=transport,
        _app_instance_id="instance",
        _lifecycle_shutdown_event=ShutdownEvent(),
        _lifecycle_session_lock=threading.Lock(),
        _lifecycle_session_ids={},
    )

    result = MainWindow._persist_lifecycle_command(window, _lifecycle_command())

    assert result.succeeded is False
    assert result.attempts == 6
    assert len(transport.failure_payloads) == 1
    assert transport.failure_payloads[0]["runtime_token"] == "instance:game-a:321:100.000000"


def test_beholder_block_is_not_retried_or_reported_as_lifecycle_failure() -> None:
    import requests
    from src.api.client import BeholderIncidentRequired
    from src.gui.main_window import MainWindow

    response = requests.Response()
    response.status_code = 409
    incident = {"id": 7, "status": "pending", "operation_kind": "runtime_start"}

    class ShutdownEvent:
        def __init__(self) -> None:
            self.delays: list[float] = []

        def is_set(self) -> bool:
            return False

        def wait(self, delay: float) -> bool:
            self.delays.append(delay)
            return False

    class Transport:
        attempts = 0

        def start_session(self, **_kwargs):
            self.attempts += 1
            raise BeholderIncidentRequired(response, incident)

        def post_json(self, *_args, **_kwargs):
            raise AssertionError("Beholder 차단은 lifecycle failure incident를 만들면 안 됩니다")

    transport = Transport()
    shutdown = ShutdownEvent()
    window = SimpleNamespace(
        _background_transport=transport,
        _app_instance_id="instance",
        _lifecycle_shutdown_event=shutdown,
        _lifecycle_session_lock=threading.Lock(),
        _lifecycle_session_ids={},
    )

    result = MainWindow._persist_lifecycle_command(window, _lifecycle_command())

    assert result.blocked is True
    assert result.beholder_incident == incident
    assert result.attempts == 1
    assert transport.attempts == 1
    assert shutdown.delays == []


def test_background_transport_preserves_beholder_409_payload(monkeypatch) -> None:
    import src.api.client as client_module
    from src.api.client import BackgroundApiTransport, BeholderIncidentRequired

    incident = {"id": 8, "status": "pending", "operation_kind": "runtime_stop"}

    class Response:
        status_code = 409
        text = "blocked"

        def json(self):
            return {"beholder_incident": incident}

        def raise_for_status(self):
            raise AssertionError("409 incident는 일반 HTTP 오류 경로로 보내면 안 됩니다")

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def request(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(client_module.requests, "Session", Session)

    with pytest.raises(BeholderIncidentRequired) as raised:
        BackgroundApiTransport("http://127.0.0.1:1").get_json("/blocked", timeout=1.0)

    assert raised.value.incident == incident


def test_incomplete_lifecycle_identity_is_rejected_without_api_call() -> None:
    from dataclasses import replace
    from src.gui.main_window import MainWindow

    command = replace(_lifecycle_command(), runtime_token="")

    class Transport:
        def start_session(self, **_kwargs):
            raise AssertionError("불완전한 lifecycle 명령은 API로 보내면 안 됩니다")

    window = SimpleNamespace(
        _background_transport=Transport(),
        _app_instance_id="instance",
        _lifecycle_shutdown_event=threading.Event(),
        _lifecycle_session_lock=threading.Lock(),
        _lifecycle_session_ids={},
    )

    result = MainWindow._persist_lifecycle_command(window, command)

    assert result.succeeded is False
    assert result.attempts == 0
    assert result.error == "invalid lifecycle identity"


def test_beholder_dialog_cannot_reenter_and_close_snoozes_for_current_run(monkeypatch) -> None:
    import src.gui.main_window as main_window_module
    from src.gui.main_window import MainWindow

    incident = {"id": 41, "status": "pending", "operation_kind": "runtime_stop"}
    opens: list[int] = []

    class Dialog:
        action = None

        def __init__(self, _incident, _parent):
            opens.append(1)

        def exec(self):
            MainWindow._apply_beholder_incidents(window, (incident,))
            return 0

    class DataManager:
        def resolve_beholder_incident(self, *_args):
            raise AssertionError("닫기/X는 DB 결정을 저장하면 안 됩니다")

    window = SimpleNamespace(
        _beholder_dialog_active=False,
        _beholder_seen_incidents=set(),
        data_manager=DataManager(),
        process_monitor=SimpleNamespace(),
        showNormal=lambda: None,
        raise_=lambda: None,
        activateWindow=lambda: None,
    )
    monkeypatch.setattr(main_window_module, "BeholderIncidentDialog", Dialog)

    MainWindow._apply_beholder_incidents(window, (incident,))
    MainWindow._apply_beholder_incidents(window, (incident,))

    assert len(opens) == 1
    assert window._beholder_dialog_active is False
    assert window._beholder_seen_incidents == {41}


def test_beholder_dialog_hides_internal_identity_until_technical_details() -> None:
    from src.gui.beholder_dialog import BeholderIncidentDialog

    _qapp()
    dialog = BeholderIncidentDialog({
        "id": 41,
        "status": "pending",
        "user_title": "이미 끝난 플레이 기록의 재종료를 차단했습니다",
        "user_summary": "삭제된 게임 항목의 기존 기록은 이미 종료되어 있습니다.",
        "user_impact": "현재 데이터는 변경되지 않았습니다.",
        "safe_recommendation": "차단을 유지하세요.",
        "operation_kind": "runtime_stop",
        "actor": "process_monitor",
        "target_summary": "session_id=1, process_id=secret-uuid",
        "current_state_summary": "status=closed",
        "proposed_change_summary": "end_timestamp=123",
        "risk_factors": ["invalid_current_status:closed"],
        "available_actions": [{
            "id": "deny",
            "label": "차단 유지",
            "description": "기존 기록을 유지합니다.",
            "outcome": "현재 데이터는 변경되지 않습니다.",
            "recommended": True,
        }],
    })

    visible_copy = "\n".join(label.text() for label in dialog.findChildren(QLabel))
    details = dialog.findChild(QTextEdit)
    button_copy = [button.text() for button in dialog.findChildren(QPushButton)]

    assert "secret-uuid" not in visible_copy
    assert "session_id" not in visible_copy
    assert details is not None and details.isHidden()
    assert "secret-uuid" in details.toPlainText()
    assert any("차단 유지" in text for text in button_copy)
    assert all("이번 한 번 허용" not in text for text in button_copy)


def test_stop_persistence_keeps_cached_resource_baseline() -> None:
    from src.gui.main_window import MainWindow, _LifecycleCommand

    event = ProcessLifecycleEvent(
        process_id="game-a",
        process_name="Game A",
        session_id=77,
        timestamp=200.0,
        stamina_tracking_enabled=True,
        hoyolab_game_id="genshin",
        pid=321,
        stamina_at_end=45,
        stamina_max=200,
        resource_tracking_enabled=True,
        resource_provider="nikke_blablalink",
        resource_key="nikke_outpost_storage",
        resource_percent_at_end=12.5,
    )
    command = _LifecycleCommand("stop", event, 321, 100.0, "instance:game-a:321:100.000000")

    class ShutdownEvent:
        def is_set(self) -> bool:
            return False

        def wait(self, _delay: float) -> bool:
            return False

    class Transport:
        def __init__(self) -> None:
            self.end_calls = []

        def end_session(self, **kwargs):
            self.end_calls.append(kwargs)
            return {"id": 77}

        def patch_json(self, *_args, **_kwargs):
            return SimpleNamespace(payload={})

    transport = Transport()
    window = SimpleNamespace(
        _background_transport=transport,
        _app_instance_id="instance",
        _lifecycle_shutdown_event=ShutdownEvent(),
        _lifecycle_session_lock=threading.Lock(),
        _lifecycle_session_ids={},
    )

    result = MainWindow._persist_lifecycle_command(window, command)

    assert result.succeeded is True
    assert transport.end_calls == [{
        "session_id": 77,
        "end_timestamp": 200.0,
        "stamina_at_end": 45,
        "resource_percent_at_end": 12.5,
        "timeout": 10.0,
    }]


def test_shell_thumbnail_balances_com_on_early_return(monkeypatch) -> None:
    class Ole32:
        def __init__(self) -> None:
            self.uninitializes = 0

        def CoInitializeEx(self, *_args) -> int:
            return 1  # S_FALSE still requires CoUninitialize.

        def CoUninitialize(self) -> None:
            self.uninitializes += 1

    class Shell32:
        def SHCreateItemFromParsingName(self, *_args) -> int:
            return 1

    ole32 = Ole32()
    monkeypatch.setattr(
        ctypes,
        "windll",
        SimpleNamespace(
            shell32=Shell32(),
            ole32=ole32,
            gdi32=SimpleNamespace(),
            user32=SimpleNamespace(),
        ),
        raising=False,
    )

    assert _VideoThumbnailLoadTask._extract_thumbnail("missing.mp4", 8, 8) is None
    assert ole32.uninitializes == 1
