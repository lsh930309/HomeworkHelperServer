"""Bounded same-thread cancellation, with an isolated native Windows pipe check."""

import os
from threading import get_ident
from types import SimpleNamespace
import uuid

import pytest

from src.host_service import transport


@pytest.fixture
def io(monkeypatch):
    if os.name == "nt":
        import pywintypes
        error_type = pywintypes.error
    else:
        class PyWinError(Exception):
            def __init__(self, code, function, message):
                super().__init__(code, function, message)
                self.winerror = code
        error_type = PyWinError
    harness = SimpleNamespace(
        error=error_type, calls=[], closed=[], stop=object(), handle=object(),
        cancellation_error=error_type(995, "GetOverlappedResult", "cancelled"),
        disconnect_error=error_type(233, "DisconnectNamedPipe", "not connected"),
        polls=0,
    )

    def record(name, *values):
        harness.calls.append((name, get_ident(), *values))

    def pending_read(handle, buffer, overlap):
        record("read", handle, overlap)
        return 997, buffer

    def pending_write(handle, data, overlap):
        record("write", handle, overlap)
        return 997, 0

    def completed(handle, overlap, wait):
        record("completion", handle, overlap, wait)
        if harness.cancellation_error is not None:
            raise harness.cancellation_error
        return 0

    def disconnect(handle):
        record("disconnect", handle)
        if harness.disconnect_error is not None:
            raise harness.disconnect_error

    def single_wait(handle, _timeout):
        if handle is harness.stop:
            harness.polls += 1
            return 258 if harness.polls == 1 else 0
        return 258

    api = SimpleNamespace(CloseHandle=harness.closed.append)
    event = SimpleNamespace(
        CreateEvent=lambda *_args: object(), WaitForSingleObject=single_wait,
        WaitForMultipleObjects=lambda *_args: 0, WAIT_OBJECT_0=0, INFINITE=-1,
    )
    file = SimpleNamespace(
        AllocateReadBuffer=bytearray, ReadFile=pending_read, WriteFile=pending_write,
        CancelIo=lambda handle: record("cancel", handle), GetOverlappedResult=completed,
    )
    pipe = SimpleNamespace(
        CreateNamedPipe=lambda *_args: harness.handle,
        ConnectNamedPipe=lambda handle, overlap: record("connect", handle, overlap) or 997,
        DisconnectNamedPipe=disconnect,
        PIPE_ACCESS_DUPLEX=3, PIPE_TYPE_MESSAGE=4, PIPE_READMODE_MESSAGE=2, PIPE_WAIT=0,
    )
    types = SimpleNamespace(OVERLAPPED=lambda: SimpleNamespace(hEvent=None),
                            SECURITY_ATTRIBUTES=SimpleNamespace, error=error_type)
    security = SimpleNamespace(
        ConvertStringSecurityDescriptorToSecurityDescriptor=lambda *_args: "descriptor",
        SDDL_REVISION_1=1,
    )
    harness.types = types
    harness.file = file
    monkeypatch.setattr(transport, "_windows", lambda: (
        types, api, SimpleNamespace(FILE_FLAG_OVERLAPPED=0x40000000, OPEN_EXISTING=3), event, file, pipe, security,
    ))
    return harness


@pytest.mark.parametrize("data", [None, b"request"])
def test_timeout_cancels_same_thread_io_and_waits_before_releasing_buffer(io, data):
    with pytest.raises(TimeoutError, match="초과"):
        transport._overlapped_io(io.handle, data=data, timeout_ms=1)
    names = [call[0] for call in io.calls]
    assert names == ["read" if data is None else "write", "cancel", "completion"]
    assert all(call[1] == get_ident() for call in io.calls)
    assert io.calls[-1][-1] is True
    assert len(io.closed) == 1


def test_cancellation_completion_race_still_reports_timeout(io):
    io.cancellation_error = None
    with pytest.raises(TimeoutError):
        transport._overlapped_io(io.handle, timeout_ms=1)
    assert [call[0] for call in io.calls] == ["read", "cancel", "completion"]


@pytest.mark.parametrize("code", [5, 109, 996])
def test_cancellation_does_not_hide_other_native_completion_failures(io, code):
    error = io.error(code, "GetOverlappedResult", "unexpected completion")
    io.cancellation_error = error
    with pytest.raises(io.error) as caught:
        transport._overlapped_io(io.handle, timeout_ms=1)
    assert caught.value is error and len(io.closed) == 1


def test_cancellation_does_not_hide_non_pywin32_error_with_abort_number(io):
    error = OSError(995, "not a native cancellation result")
    error.winerror = 995
    io.cancellation_error = error
    with pytest.raises(OSError) as caught:
        transport._overlapped_io(io.handle, timeout_ms=1)
    assert caught.value is error


def test_service_stop_cancels_listening_pipe_without_error_log_or_request(io):
    errors = []
    controller = SimpleNamespace(owner_sid="owner")  # Stop must precede authentication/dispatch.
    transport.NamedPipeServer(controller, io.stop, log_error=errors.append).run()
    assert errors == []
    assert [call[0] for call in io.calls] == ["connect", "cancel", "completion", "disconnect"]
    assert all(call[1] == get_ident() for call in io.calls)
    assert io.closed[-1] is io.handle and len(io.closed) == 2


def test_service_stop_logs_unexpected_cancellation_error(io):
    errors = []
    error = io.error(5, "GetOverlappedResult", "access denied")
    io.cancellation_error = error
    transport.NamedPipeServer(SimpleNamespace(owner_sid="owner"), io.stop, log_error=errors.append).run()
    assert errors == [str(error)] and len(io.closed) == 2


@pytest.mark.parametrize("error_kind", ["native", "os"])
def test_service_cleanup_propagates_other_disconnect_errors_and_closes_handles(io, error_kind):
    if error_kind == "native":
        error = io.error(5, "DisconnectNamedPipe", "access denied")
    else:
        error = OSError(233, "not a native disconnected result")
        error.winerror = 233
    io.disconnect_error = error
    with pytest.raises(type(error)) as caught:
        transport.NamedPipeServer(SimpleNamespace(owner_sid="owner"), io.stop).run()
    assert caught.value is error
    assert io.closed[-1] is io.handle and len(io.closed) == 2


@pytest.mark.parametrize("code", [2, 231])
def test_connection_retries_only_transient_acquisition_failures(io, monkeypatch, code):
    _types, _api, con, _event, file, pipe, _security = transport._windows()
    con.OPEN_EXISTING = 3
    calls = []

    def open_pipe(*_args):
        calls.append("open")
        if len(calls) == 1:
            raise io.error(code, "CreateFile", "not available yet")
        return io.handle

    file.CreateFile = open_pipe
    pipe.WaitNamedPipe = lambda *_args: calls.append("wait")
    monkeypatch.setattr(transport.time, "sleep", lambda _seconds: None)
    assert transport._connect_pipe() is io.handle
    assert calls == (["open", "open"] if code == 2 else ["open", "wait", "open"])


def test_connection_absence_obeys_one_total_deadline(io, monkeypatch):
    _types, _api, con, _event, file, _pipe, _security = transport._windows()
    con.OPEN_EXISTING = 3
    clock = SimpleNamespace(now=0.0)
    calls = []

    def open_pipe(*_args):
        calls.append(clock.now)
        raise io.error(2, "CreateFile", "absent")

    file.CreateFile = open_pipe
    monkeypatch.setattr(transport, "IPC_TIMEOUT_MS", 50)
    monkeypatch.setattr(transport, "time", SimpleNamespace(
        monotonic=lambda: clock.now, sleep=lambda seconds: setattr(clock, "now", clock.now + seconds)))
    with pytest.raises(io.error) as caught:
        transport._connect_pipe()
    assert caught.value.winerror == 2
    assert clock.now == pytest.approx(0.05)
    assert len(calls) == 3


def test_access_denied_is_not_retried_and_native_details_are_reported(io):
    from src.host_service.client import HostPrivilegeClient, PrivilegeServiceUnavailable
    _types, _api, con, _event, file, _pipe, _security = transport._windows()
    con.OPEN_EXISTING = 3
    calls = []

    def open_pipe(*_args):
        calls.append("open")
        raise io.error(5, "CreateFile", "access denied")

    file.CreateFile = open_pipe
    with pytest.raises(PrivilegeServiceUnavailable, match="CreateFile") as caught:
        HostPrivilegeClient().status()
    assert "5" in str(caught.value)
    assert calls == ["open"]


@pytest.mark.parametrize("failure_at", ["write", "read", "ack"])
def test_unknown_command_outcome_is_never_replayed(io, monkeypatch, failure_at):
    _types, _api, _con, _event, _file, pipe, _security = transport._windows()
    pipe.SetNamedPipeHandleState = lambda *_args: None
    opens, exchanges = [], []
    monkeypatch.setattr(transport, "_connect_pipe", lambda: opens.append(1) or io.handle)

    def exchange(_handle, *, data=None, **_kwargs):
        stage = "read" if data is None else "ack" if b"received" in data else "write"
        exchanges.append(stage)
        if stage == failure_at:
            raise io.error(109, stage, "broken pipe")
        return b'{"accepted":true}' if data is None else len(data)

    monkeypatch.setattr(transport, "_overlapped_io", exchange)
    with pytest.raises(OSError):
        transport.pipe_request({"operation": "power", "action": "shutdown"})
    assert opens == [1]
    assert exchanges == ["write", "read", "ack"][:exchanges.index(failure_at) + 1]
    assert io.closed == [io.handle]


@pytest.mark.skipif(os.name != "nt", reason="Requires actual Windows overlapped named pipe API")
def test_actual_windows_can_cancel_its_own_isolated_listening_pipe():
    import pywintypes
    import win32api
    import win32con
    import win32event
    import win32file
    import win32pipe

    assert callable(win32file.CancelIo)
    # A unique test pipe cannot affect HomeworkHelper's installed service pipe or another run.
    name = rf"\\.\pipe\HomeworkHelper-cancel-test-{uuid.uuid4()}"
    handle = win32pipe.CreateNamedPipe(
        name, win32pipe.PIPE_ACCESS_DUPLEX | win32con.FILE_FLAG_OVERLAPPED,
        win32pipe.PIPE_TYPE_BYTE | win32pipe.PIPE_READMODE_BYTE | win32pipe.PIPE_WAIT,
        1, 4096, 4096, 0, None,
    )
    overlap = pywintypes.OVERLAPPED()
    overlap.hEvent = win32event.CreateEvent(None, True, False, None)
    try:
        try:
            win32pipe.ConnectNamedPipe(handle, overlap)
        except pywintypes.error as error:
            if error.winerror != 997:
                raise
        with pytest.raises(pywintypes.error) as pending:
            win32file.GetOverlappedResult(handle, overlap, False)
        assert pending.value.winerror == 996  # ERROR_IO_INCOMPLETE before same-thread cancellation.
        transport._cancel_owned_io(handle, overlap)
        assert win32event.WaitForSingleObject(overlap.hEvent, 0) == win32event.WAIT_OBJECT_0
        with pytest.raises(pywintypes.error) as finished:
            win32file.GetOverlappedResult(handle, overlap, False)
        assert finished.value.winerror == 995
        try:
            win32pipe.DisconnectNamedPipe(handle)
        except pywintypes.error as error:
            assert error.winerror == 233
    finally:
        try:
            win32api.CloseHandle(handle)
        finally:
            win32api.CloseHandle(overlap.hEvent)


@pytest.mark.skipif(__import__('os').name != 'nt', reason='Requires native Windows named pipes')
def test_native_windows_already_connected_return_and_error_normalization(monkeypatch):
    import uuid
    import pywintypes, win32api, win32con, win32event, win32file, win32pipe
    from src.host_service.client import HostPrivilegeClient, PrivilegeServiceUnavailable
    name = r'\\.\pipe\HHIsolated-' + uuid.uuid4().hex
    server = win32pipe.CreateNamedPipe(name, win32pipe.PIPE_ACCESS_DUPLEX | win32con.FILE_FLAG_OVERLAPPED,
        win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT | 8,
        1,4096,4096,1000,None)
    client = event = None
    try:
        client = win32file.CreateFile(name,win32con.GENERIC_READ | win32con.GENERIC_WRITE,0,None,
                                    win32con.OPEN_EXISTING,win32con.FILE_FLAG_OVERLAPPED,None)
        overlap = pywintypes.OVERLAPPED()
        event = overlap.hEvent = win32event.CreateEvent(None,True,False,None)
        try: result = win32pipe.ConnectNamedPipe(server,overlap)
        except pywintypes.error as error: result = error.winerror
        assert result == 535
    finally:
        if client is not None: win32api.CloseHandle(client)
        if event is not None: win32api.CloseHandle(event)
        win32api.CloseHandle(server)
    monkeypatch.setattr(transport,'PIPE_NAME',name+'-absent')
    monkeypatch.setattr(transport,'IPC_TIMEOUT_MS',50)
    with pytest.raises(PrivilegeServiceUnavailable): HostPrivilegeClient().status()


@pytest.mark.skipif(os.name != "nt", reason="Requires actual concurrent Windows pipe clients")
def test_windows_competing_clients_both_complete_without_replaying_requests(monkeypatch):
    import threading
    import pywintypes, win32api, win32event, win32file, win32pipe, win32security
    from src.host_service.controller import Reply

    name = rf"\\.\pipe\HH-monitor-race-{uuid.uuid4()}"
    monkeypatch.setattr(transport, "PIPE_NAME", name)
    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), 8)
    try:
        sid = win32security.ConvertSidToStringSid(win32security.GetTokenInformation(token, 1)[0])
    finally:
        token.Close()
    ready = threading.Event()
    busy = threading.Event()
    barrier = threading.Barrier(2)
    seen = threading.local()
    real_create_pipe = win32pipe.CreateNamedPipe
    real_wait = win32pipe.WaitNamedPipe
    real_open = win32file.CreateFile
    creations, requests, results, failures, errors = [], [], [], [], []

    def create_pipe(*args):
        handle = real_create_pipe(*args)
        creations.append(handle)
        ready.set()
        return handle

    def wait_pipe(*args):
        return real_wait(*args)

    def open_pipe(*args):
        if not getattr(seen, "opened", False):
            seen.opened = True
            barrier.wait(2.0)  # Both clients try to acquire the same available instance.
        try:
            return real_open(*args)
        except pywintypes.error as error:
            if error.winerror == 231:
                busy.set()
            raise

    def handle(request, _caller):
        requests.append(request["id"])
        assert busy.wait(2.0), "The competing client must encounter real ERROR_PIPE_BUSY"
        return Reply({"accepted": True, "id": request["id"]})

    monkeypatch.setattr(win32pipe, "CreateNamedPipe", create_pipe)
    monkeypatch.setattr(win32pipe, "WaitNamedPipe", wait_pipe)
    monkeypatch.setattr(win32file, "CreateFile", open_pipe)
    stop = win32event.CreateEvent(None, True, False, None)
    controller = SimpleNamespace(owner_sid=sid, backend=SimpleNamespace(authenticate=lambda _h: None), handle=handle)
    server = threading.Thread(target=transport.NamedPipeServer(controller, stop, log_error=errors.append).run)

    def client(identity):
        try:
            results.append(transport.pipe_request({"operation": "status", "id": identity}))
        except Exception as error:
            failures.append(error)

    clients = [threading.Thread(target=client, args=(identity,)) for identity in (1, 2)]
    server.start()
    try:
        assert ready.wait(2.0)
        for thread in clients:
            thread.start()
        for thread in clients:
            thread.join(8.0)
        assert not any(thread.is_alive() for thread in clients)
        assert busy.is_set()
        assert failures == [], [(type(error).__name__, str(error)) for error in failures]
        assert sorted(item["id"] for item in results) == [1, 2]
        assert sorted(requests) == [1, 2]  # No command replay after request transmission.
        assert len(creations) == 1  # No absent-pipe interval between clients.
        assert errors == []
    finally:
        busy.set()
        win32event.SetEvent(stop)
        for thread in clients:
            if thread.ident is not None:
                thread.join(8.0)
        server.join(8.0)
        assert not server.is_alive()
        win32api.CloseHandle(stop)
