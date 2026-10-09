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
        ConnectNamedPipe=lambda handle, overlap: record("connect", handle, overlap),
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
        types, api, SimpleNamespace(FILE_FLAG_OVERLAPPED=0x40000000), event, file, pipe, security,
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
    assert io.closed[0] is io.handle and len(io.closed) == 2


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
    assert io.closed[0] is io.handle and len(io.closed) == 2


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
