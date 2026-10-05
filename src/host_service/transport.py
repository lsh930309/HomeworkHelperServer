"""Bounded local named-pipe transport; Windows imports occur only when used."""

from __future__ import annotations

import json
import os

from .constants import IPC_TIMEOUT_MS, MAX_MESSAGE_BYTES, PIPE_NAME
from .controller import RequestDenied


def _windows():
    if os.name != "nt":
        raise OSError("Windows 권한 서비스는 Windows에서만 사용할 수 있습니다.")
    import pywintypes
    import win32api
    import win32con
    import win32event
    import win32file
    import win32pipe
    import win32security
    return pywintypes, win32api, win32con, win32event, win32file, win32pipe, win32security


def encode_message(value) -> bytes:
    data = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(data) > MAX_MESSAGE_BYTES:
        raise ValueError("IPC 메시지가 너무 큽니다.")
    return data


def decode_message(data: bytes) -> dict:
    if len(data) > MAX_MESSAGE_BYTES:
        raise ValueError("IPC 메시지가 너무 큽니다.")
    value = json.loads(data.decode("utf-8"), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    if not isinstance(value, dict):
        raise ValueError("IPC 메시지는 JSON 객체여야 합니다.")
    return value


def _overlapped_io(handle, *, data=None, timeout_ms=IPC_TIMEOUT_MS):
    pywintypes, win32api, _con, win32event, win32file, _pipe, _security = _windows()
    overlap = pywintypes.OVERLAPPED()
    overlap.hEvent = win32event.CreateEvent(None, True, False, None)
    try:
        if data is None:
            buffer = win32file.AllocateReadBuffer(MAX_MESSAGE_BYTES)
            result, _ = win32file.ReadFile(handle, buffer, overlap)
        else:
            buffer = data
            result, _ = win32file.WriteFile(handle, buffer, overlap)
        if result == 997:
            if win32event.WaitForSingleObject(overlap.hEvent, timeout_ms) != win32event.WAIT_OBJECT_0:
                win32file.CancelIoEx(handle, overlap)
                # Keep buffer alive until cancellation completed.
                try:
                    win32file.GetOverlappedResult(handle, overlap, True)
                except OSError:
                    pass
                raise TimeoutError("권한 서비스 IPC 응답 시간이 초과되었습니다.")
        count = win32file.GetOverlappedResult(handle, overlap, False)
        return bytes(buffer[:count]) if data is None else count
    finally:
        win32api.CloseHandle(overlap.hEvent)


def pipe_request(request: dict, *, before_ack=None) -> dict:
    _types, win32api, win32con, _event, win32file, win32pipe, _security = _windows()
    win32pipe.WaitNamedPipe(PIPE_NAME, IPC_TIMEOUT_MS)
    handle = win32file.CreateFile(
        PIPE_NAME, 0x12019b, 0, None,  # Read/write without FILE_CREATE_PIPE_INSTANCE
        win32con.OPEN_EXISTING,
        win32con.FILE_FLAG_OVERLAPPED | 0x00100000 | 0x00010000,  # SQOS_PRESENT | IDENTIFICATION
        None,
    )
    try:
        win32pipe.SetNamedPipeHandleState(handle, win32pipe.PIPE_READMODE_MESSAGE, None, None)
        _overlapped_io(handle, data=encode_message(request))
        response = decode_message(_overlapped_io(handle, timeout_ms=15000))
        if before_ack is not None:
            before_ack(response)
        _overlapped_io(handle, data=encode_message({"received":True}))
        return response
    finally:
        win32api.CloseHandle(handle)


class NamedPipeServer:
    def __init__(self, controller, stop_event, *, log_error=None):
        self.controller = controller
        self.stop_event = stop_event
        self.log_error = log_error or (lambda message: None)

    def run(self):
        types, win32api, con, event, file, pipe, security = _windows()
        sd = security.ConvertStringSecurityDescriptorToSecurityDescriptor(
            # Strip FILE_CREATE_PIPE_INSTANCE from user rights to prevent competing servers.
            f"D:P(A;;GA;;;SY)(A;;0x12019b;;;{self.controller.owner_sid})",
            security.SDDL_REVISION_1,
        )
        attributes = types.SECURITY_ATTRIBUTES()
        attributes.SECURITY_DESCRIPTOR = sd
        while event.WaitForSingleObject(self.stop_event, 0) != event.WAIT_OBJECT_0:
            handle = pipe.CreateNamedPipe(
                PIPE_NAME, pipe.PIPE_ACCESS_DUPLEX | con.FILE_FLAG_OVERLAPPED | 0x00080000,
                pipe.PIPE_TYPE_MESSAGE | pipe.PIPE_READMODE_MESSAGE | pipe.PIPE_WAIT | 0x00000008,
                1, MAX_MESSAGE_BYTES, MAX_MESSAGE_BYTES, IPC_TIMEOUT_MS, attributes,
            )
            overlap = types.OVERLAPPED()
            overlap.hEvent = event.CreateEvent(None, True, False, None)
            reply = None
            try:
                try:
                    pipe.ConnectNamedPipe(handle, overlap)
                except OSError as error:
                    if getattr(error, "winerror", error.args[0]) == 535:  # already connected
                        event.SetEvent(overlap.hEvent)
                    elif getattr(error, "winerror", error.args[0]) != 997:
                        raise
                waited = event.WaitForMultipleObjects((self.stop_event, overlap.hEvent), False, event.INFINITE)
                if waited == event.WAIT_OBJECT_0:
                    file.CancelIoEx(handle, overlap)
                    try:
                        file.GetOverlappedResult(handle, overlap, True)
                    except OSError:
                        pass
                    return
                request = decode_message(_overlapped_io(handle))
                caller = self.controller.backend.authenticate(handle)
                try:
                    reply = self.controller.handle(request, caller)
                    payload = reply.payload
                except (RequestDenied, LookupError) as error:
                    payload = {"accepted":False, "status":"denied", "message":str(error)}
                except NotImplementedError as error:
                    payload = {"accepted":False, "status":"unsupported", "message":str(error)}
                except TimeoutError as error:
                    payload = {"accepted":False, "status":"unknown", "message":str(error)}
                except PermissionError as error:
                    payload = {"accepted":False, "status":"denied", "message":str(error)}
                except Exception as error:
                    self.log_error(str(error))
                    payload = {"accepted":False, "status":"error", "message":"권한 작업을 수행하지 못했습니다."}
                _overlapped_io(handle, data=encode_message(payload))
                if decode_message(_overlapped_io(handle)) != {"received":True}:
                    raise ValueError("권한 서비스 응답 수신 확인이 올바르지 않습니다.")
            except Exception as error:
                self.log_error(str(error))
                reply = None
            finally:
                try:
                    pipe.DisconnectNamedPipe(handle)
                except OSError:
                    pass
                win32api.CloseHandle(handle)
                win32api.CloseHandle(overlap.hEvent)
            if reply is not None and reply.after_send is not None:
                try:
                    reply.after_send()
                except Exception as error:
                    self.log_error(f"Accepted action failed: {error}")
