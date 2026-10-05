"""Native Windows operations for the local privilege service.

This module has no GUI or database imports. Windows modules are loaded only
when a native operation is requested, so controller tests run on other OSes.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
from functools import lru_cache
import json
import ntpath
import os
from pathlib import Path
import stat
import subprocess
from types import SimpleNamespace
import uuid

from .constants import APP_EXE, REGISTRY_PARAMETERS, SERVICE_EXE, SYSTEM_SID
from .controller import Caller, ProcessIdentity, Session


_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_PROCESS_TERMINATE = 0x0001
_TOKEN_QUERY = 0x0008
_FILETIME_UNIX_EPOCH = 116444736000000000
_TRUSTED_INSTALLER_SID = "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464"
_PROTECTED_WRITERS = frozenset({SYSTEM_SID, "S-1-5-32-544", _TRUSTED_INSTALLER_SID})
# File/directory writes, deletion, ACL/owner changes, and generic write/all.
_MUTATING_FILE_RIGHTS = 0x520D0156


class _BatteryReportingScale(ctypes.Structure):
    _fields_ = [("Granularity", ctypes.c_uint32), ("Capacity", ctypes.c_uint32)]


class _PowerCapabilities(ctypes.Structure):
    # SYSTEM_POWER_CAPABILITIES (winnt.h). Fixed-width fields preserve the Windows
    # ABI in platform-independent tests too; BOOLEAN is one byte, not C bool/int.
    _fields_ = [
        (name, ctypes.c_ubyte) for name in (
            "PowerButtonPresent", "SleepButtonPresent", "LidPresent", "SystemS1",
            "SystemS2", "SystemS3", "SystemS4", "SystemS5", "HiberFilePresent",
            "FullWake", "VideoDimPresent", "ApmPresent", "UpsPresent", "ThermalControl",
            "ProcessorThrottle", "ProcessorMinThrottle", "ProcessorMaxThrottle",
            "FastSystemS4", "Hiberboot", "WakeAlarmPresent", "AoAc", "DiskSpinDown",
            "HiberFileType", "AoAcConnectivitySupported",
        )
    ] + [
        ("spare3", ctypes.c_ubyte * 6), ("SystemBatteriesPresent", ctypes.c_ubyte),
        ("BatteriesAreShortTerm", ctypes.c_ubyte), ("BatteryScale", _BatteryReportingScale * 3),
    ] + [(name, ctypes.c_uint32) for name in (
        "AcOnLineWake", "SoftLidWake", "RtcWake", "MinDeviceWakeState", "DefaultLowLatencyWake",
    )]


def _power_capabilities() -> _PowerCapabilities:
    native = ctypes.WinDLL("powrprof", use_last_error=True)
    native.GetPwrCapabilities.argtypes = [ctypes.POINTER(_PowerCapabilities)]
    native.GetPwrCapabilities.restype = ctypes.c_ubyte
    capabilities = _PowerCapabilities()
    if not native.GetPwrCapabilities(ctypes.byref(capabilities)):
        raise ctypes.WinError(ctypes.get_last_error())
    return capabilities


@lru_cache(maxsize=1)
def _win32():
    if os.name != "nt":
        raise RuntimeError("Windows native service operations require Windows.")
    import psutil
    import pywintypes
    import win32api
    import win32con
    import win32event
    import win32pipe
    import win32process
    import win32profile
    import win32security
    import win32ts

    return SimpleNamespace(
        psutil=psutil, api=win32api, con=win32con, pipe=win32pipe,
        process=win32process, profile=win32profile, security=win32security,
        event=win32event,
        ts=win32ts, error=pywintypes.error,
    )


@lru_cache(maxsize=1)
def _kernel32():
    native = ctypes.WinDLL("kernel32", use_last_error=True)
    native.GetNamedPipeClientProcessId.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG),
    ]
    native.GetNamedPipeClientProcessId.restype = wintypes.BOOL
    native.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    native.QueryFullProcessImageNameW.restype = wintypes.BOOL
    native.GetProcessTimes.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    ]
    native.GetProcessTimes.restype = wintypes.BOOL
    return native


def _close(handle) -> None:
    if handle is not None:
        handle.Close()


def _enable_privileges(*names: str) -> None:
    api = _win32()
    security = api.security
    token = security.OpenProcessToken(
        api.api.GetCurrentProcess(),
        security.TOKEN_ADJUST_PRIVILEGES | security.TOKEN_QUERY,
    )
    try:
        privileges = [
            (security.LookupPrivilegeValue(None, name), security.SE_PRIVILEGE_ENABLED)
            for name in names
        ]
        security.AdjustTokenPrivileges(token, False, privileges)
        # The API can succeed while declining an unavailable privilege.
        if api.api.GetLastError() == 1300:  # ERROR_NOT_ALL_ASSIGNED
            raise PermissionError("The service token lacks a required Windows privilege.")
    finally:
        _close(token)


def _token_sid(token) -> str:
    security = _win32().security
    sid, _attributes = security.GetTokenInformation(token, security.TokenUser)
    return security.ConvertSidToStringSid(sid)


def _token_session(token) -> int:
    security = _win32().security
    return int(security.GetTokenInformation(token, security.TokenSessionId))


def _token_logon_id(token) -> str:
    security = _win32().security
    statistics = security.GetTokenInformation(token, security.TokenStatistics)
    return str(statistics["AuthenticationId"])


def _image_path(handle) -> str:
    buffer = ctypes.create_unicode_buffer(32768)
    size = wintypes.DWORD(len(buffer))
    if not _kernel32().QueryFullProcessImageNameW(int(handle), 0, buffer, ctypes.byref(size)):
        raise ctypes.WinError(ctypes.get_last_error())
    return buffer.value


def _creation_time(handle) -> float:
    created, exited = wintypes.FILETIME(), wintypes.FILETIME()
    kernel, user = wintypes.FILETIME(), wintypes.FILETIME()
    if not _kernel32().GetProcessTimes(
        int(handle), ctypes.byref(created), ctypes.byref(exited),
        ctypes.byref(kernel), ctypes.byref(user),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    ticks = (created.dwHighDateTime << 32) | created.dwLowDateTime
    return (ticks - _FILETIME_UNIX_EPOCH) / 10_000_000


def _process_identity(handle, pid: int) -> ProcessIdentity:
    security = _win32().security
    token = security.OpenProcessToken(handle, _TOKEN_QUERY)
    try:
        return ProcessIdentity(
            pid=pid, create_time=_creation_time(handle), path=_image_path(handle),
            sid=_token_sid(token), session_id=_token_session(token),
        )
    finally:
        _close(token)


def _known_folder_path(folder_id: str, token=None) -> Path:
    """Read an OS-owned known-folder location without materializing it."""
    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
            ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8),
        ]

    folder = GUID.from_buffer_copy(uuid.UUID(folder_id).bytes_le)
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    shell.SHGetKnownFolderPath.argtypes = [
        ctypes.POINTER(GUID), wintypes.DWORD, wintypes.HANDLE,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    shell.SHGetKnownFolderPath.restype = ctypes.c_long
    ole = ctypes.WinDLL("ole32")
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole.CoTaskMemFree.restype = None
    result = ctypes.c_void_p()
    # KF_FLAG_DONT_VERIFY: a read of a known folder must not materialize it.
    hr = shell.SHGetKnownFolderPath(
        ctypes.byref(folder), 0x4000, int(token) if token is not None else None,
        ctypes.byref(result),
    )
    try:
        if hr < 0:
            raise OSError(f"SHGetKnownFolderPath failed (HRESULT 0x{hr & 0xffffffff:08x}).")
        if not result.value:
            raise OSError("Windows did not return the requested known-folder directory.")
        return Path(ctypes.wstring_at(result))
    finally:
        if result.value:
            ole.CoTaskMemFree(result)


def _roaming_appdata(token) -> Path:
    return _known_folder_path("3EB685DB-65F9-4CF6-A03A-E3EF65729F3D", token) / "HomeworkHelper"


def _program_files_roots() -> tuple[Path, ...]:
    # The OS defines these paths; environment variables are not a trust boundary.
    return tuple({
        _known_folder_path("905E63B6-C1BF-494E-B29C-65B732D3D21A").resolve(strict=True),
        _known_folder_path("7C5A40EF-A0FB-4BFC-874A-C0F2E0B9FAE").resolve(strict=True),
    })


def _check_protected_file_acl(path: Path) -> None:
    security = _win32().security
    descriptor = security.GetNamedSecurityInfo(
        str(path), security.SE_FILE_OBJECT,
        security.OWNER_SECURITY_INFORMATION | security.DACL_SECURITY_INFORMATION,
    )
    owner = security.ConvertSidToStringSid(descriptor.GetSecurityDescriptorOwner())
    if owner not in _PROTECTED_WRITERS:
        raise PermissionError(f"The service runtime has an untrusted owner: {path}")
    dacl = descriptor.GetSecurityDescriptorDacl()
    if dacl is None:
        raise PermissionError(f"The service runtime has an unrestricted null DACL: {path}")
    for index in range(dacl.GetAceCount()):
        try:
            ace = dacl.GetAce(index)
        except NotImplementedError as error:
            raise PermissionError(f"The runtime ACL cannot be verified: {path}") from error
        ace_type, flags = ace[0]
        if flags & 0x08:  # INHERIT_ONLY_ACE does not apply to the current object.
            continue
        if ace_type in {1, 6}:  # Deny and deny-object ACEs only restrict access.
            continue
        if ace_type not in {0, 5}:
            raise PermissionError(f"The runtime ACL contains an unsupported access entry: {path}")
        if not ace[1] & _MUTATING_FILE_RIGHTS:
            continue
        trustee = security.ConvertSidToStringSid(ace[-1])
        if trustee == "S-1-3-4":  # OWNER RIGHTS refers to the checked object owner.
            trustee = owner
        if trustee not in _PROTECTED_WRITERS:
            raise PermissionError(f"An ordinary account can modify the service runtime: {path}")


def validate_protected_install(service_exe: Path) -> None:
    """Reject a SYSTEM service installation that a normal user could replace.

    The complete install tree is executable input, including the packaged Python
    runtime and imported modules. Checking just the EXE or a Program Files prefix
    would leave writable DLLs and parent-directory replacement paths unprotected.
    """
    supplied = Path(service_exe).absolute()
    root = next((candidate for candidate in _program_files_roots()
                 if supplied.is_relative_to(candidate)), None)
    if root is None or supplied.parent == root:
        raise PermissionError("Install the Windows service in a protected Program Files application directory.")
    resolved = supplied.resolve(strict=True)
    if ntpath.normcase(str(supplied)) != ntpath.normcase(str(resolved)) or not resolved.is_file():
        raise PermissionError("The service executable must not use a symbolic-link or junction alias.")
    install_dir = resolved.parent
    ancestors = []
    current = install_dir.parent
    while current.is_relative_to(root):
        ancestors.append(current)
        if current == root:
            break
        current = current.parent
    pending = [install_dir, *ancestors]
    while pending:
        path = pending.pop()
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise PermissionError(f"The service runtime must not include reparse points: {path}")
        _check_protected_file_acl(path)
        # Ancestors are checked, but unrelated applications under Program Files
        # are outside this installation's executable-input boundary.
        if path.is_relative_to(install_dir) and stat.S_ISDIR(info.st_mode):
            pending.extend(path.iterdir())


def read_owner_sid() -> str | None:
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, REGISTRY_PARAMETERS, 0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        ) as key:
            value, value_type = winreg.QueryValueEx(key, "OwnerSid")
    except FileNotFoundError:
        return None
    if value_type != winreg.REG_SZ or not isinstance(value, str):
        raise ValueError("The installed service OwnerSid is not a registry string.")
    _win32().security.ConvertStringSidToSid(value)
    return value


def write_owner_sid(owner: str) -> str:
    """Resolve an account once during installation and persist only its SID."""
    import winreg

    security = _win32().security
    if owner.startswith("S-1-"):
        sid = security.ConvertStringSidToSid(owner)
        _name, _domain, account_type = security.LookupAccountSid(None, sid)
    else:
        sid, _domain, account_type = security.LookupAccountName(None, owner)
    if account_type != security.SidTypeUser:
        raise ValueError("The service owner must be a Windows user account.")
    sid_text = security.ConvertSidToStringSid(sid)
    if sid_text in {"S-1-5-18", "S-1-5-19", "S-1-5-20"}:
        raise ValueError("A Windows service account cannot own the desktop app.")
    with winreg.CreateKeyEx(
        winreg.HKEY_LOCAL_MACHINE, REGISTRY_PARAMETERS, 0,
        winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY,
    ) as key:
        winreg.SetValueEx(key, "OwnerSid", 0, winreg.REG_SZ, sid_text)
    return sid_text


def remove_owner_sid() -> None:
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, REGISTRY_PARAMETERS, 0,
            winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY,
        ) as key:
            winreg.DeleteValue(key, "OwnerSid")
    except FileNotFoundError:
        pass


class WindowsBackend:
    def __init__(
        self, install_dir: Path, service_exe: Path | None = None,
        app_exe: Path | None = None,
    ) -> None:
        self.install_dir = Path(install_dir).resolve()
        self.service_exe = Path(service_exe or self.install_dir / SERVICE_EXE).resolve()
        self.app_exe = Path(app_exe or self.install_dir / APP_EXE).resolve()

    def sessions(self, owner_sid: str) -> list[Session]:
        api = _win32()
        _enable_privileges("SeTcbPrivilege")
        session_id = int(api.ts.WTSGetActiveConsoleSessionId())
        if session_id == 0xffffffff:
            return []
        try:
            token = api.ts.WTSQueryUserToken(session_id)
        except (OSError, api.error) as exc:
            if getattr(exc, "winerror", None) in {87, 1008, 7022}:
                return []
            raise
        try:
            if _token_sid(token) != owner_sid or _token_session(token) != session_id:
                return []
            return [Session(owner_sid, session_id, _roaming_appdata(token), _token_logon_id(token))]
        finally:
            _close(token)

    def current_session(self, owner_sid: str) -> Session | None:
        sessions = self.sessions(owner_sid)
        return sessions[0] if sessions else None

    def authenticate(self, pipe_handle) -> Caller:
        api = _win32()
        client_pid = wintypes.ULONG()
        if not _kernel32().GetNamedPipeClientProcessId(int(pipe_handle), ctypes.byref(client_pid)):
            raise ctypes.WinError(ctypes.get_last_error())
        # Obtain the pipe endpoint's token, not just a potentially recycled PID.
        api.pipe.ImpersonateNamedPipeClient(pipe_handle)
        token = None
        try:
            token = api.security.OpenThreadToken(
                api.api.GetCurrentThread(), _TOKEN_QUERY, True,
            )
            pipe_sid, pipe_session = _token_sid(token), _token_session(token)
            pipe_logon_id = _token_logon_id(token)
        finally:
            try:
                api.security.RevertToSelf()
            finally:
                _close(token)
        process = api.api.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, client_pid.value)
        try:
            identity = _process_identity(process, client_pid.value)
            process_token = api.security.OpenProcessToken(process, _TOKEN_QUERY)
            try:
                process_logon_id = _token_logon_id(process_token)
            finally:
                _close(process_token)
        finally:
            _close(process)
        if (
            identity.sid != pipe_sid or identity.session_id != pipe_session
            or process_logon_id != pipe_logon_id
        ):
            raise PermissionError("The pipe endpoint and its process identity do not match.")
        return Caller(
            pid=identity.pid, sid=identity.sid, session_id=identity.session_id,
            image_path=identity.path, logon_id=process_logon_id,
        )

    @contextmanager
    def _user_token(self, session: Session, elevated: bool):
        api = _win32()
        security = api.security
        _enable_privileges(
            "SeTcbPrivilege", "SeAssignPrimaryTokenPrivilege", "SeIncreaseQuotaPrivilege",
        )
        token = api.ts.WTSQueryUserToken(session.session_id)
        linked = primary = None
        try:
            if (_token_sid(token), _token_session(token)) != (session.owner_sid, session.session_id):
                raise PermissionError("The requested user session has ended or changed.")
            if session.logon_id is not None and _token_logon_id(token) != session.logon_id:
                raise PermissionError("The requested Windows logon session has ended.")
            token_elevated = bool(security.GetTokenInformation(token, security.TokenElevation))
            selected = token
            if token_elevated != elevated:
                elevation_type = security.GetTokenInformation(token, security.TokenElevationType)
                if elevation_type == security.TokenElevationTypeDefault:
                    raise PermissionError("The requested user token is not available.")
                linked = security.GetTokenInformation(token, security.TokenLinkedToken)
                selected = linked
            if bool(security.GetTokenInformation(selected, security.TokenElevation)) != elevated:
                raise PermissionError("Windows did not provide the requested user privilege level.")
            if (_token_sid(selected), _token_session(selected)) != (session.owner_sid, session.session_id):
                raise PermissionError("The linked token belongs to a different user session.")
            primary = security.DuplicateTokenEx(
                selected, security.SecurityImpersonation,
                security.TOKEN_ALL_ACCESS, security.TokenPrimary,
            )
            yield primary
        finally:
            _close(primary)
            _close(linked)
            _close(token)

    @contextmanager
    def read_as_user(self, session: Session):
        """Read the owner's existing profile files with the owner's access token."""
        security = _win32().security
        with self._user_token(session, elevated=False) as token:
            security.ImpersonateLoggedOnUser(token)
            try:
                yield
            finally:
                security.RevertToSelf()

    def _create_user_process(
        self, session: Session, executable: Path, arguments: list[str], *, elevated: bool,
        wait_for_worker: bool = False,
    ) -> dict:
        api = _win32()
        with self._user_token(session, elevated) as token:
            current = self.current_session(session.owner_sid)
            if (
                current is None or current.session_id != session.session_id
                or current.logon_id != session.logon_id
            ):
                raise PermissionError("The requested console session is no longer active.")
            environment = api.profile.CreateEnvironmentBlock(token, False)
            startup = api.process.STARTUPINFO()
            startup.lpDesktop = r"winsta0\default"
            process = thread = None
            try:
                process, thread, pid, _thread_id = api.process.CreateProcessAsUser(
                    token, str(executable), subprocess.list2cmdline([str(executable), *arguments]),
                    None, None, False,
                    api.con.CREATE_UNICODE_ENVIRONMENT | api.con.CREATE_NO_WINDOW,
                    environment, str(self.install_dir), startup,
                )
                if wait_for_worker:
                    waited = api.event.WaitForSingleObject(process, 10_000)
                    if waited == api.event.WAIT_TIMEOUT:
                        # Clean up only this short-lived helper. A game might have
                        # started already; never terminate or automatically retry it.
                        try:
                            api.process.TerminateProcess(process, 1)
                            cleanup = api.event.WaitForSingleObject(process, 2_000)
                            if cleanup != api.event.WAIT_OBJECT_0:
                                raise OSError("The launch worker did not stop after its cleanup request.")
                        except Exception as error:
                            raise TimeoutError(
                                "The launch result is unknown; worker cleanup failed. Do not retry automatically."
                            ) from error
                        raise TimeoutError(
                            "The launch result is unknown; the timed-out worker was stopped. Do not retry automatically."
                        )
                    if waited != api.event.WAIT_OBJECT_0:
                        raise OSError("Unable to observe the user launch worker result.")
                    exit_code = api.process.GetExitCodeProcess(process)
                    if exit_code != 0:
                        raise RuntimeError(f"The user launch worker failed (exit code {exit_code}).")
                    return {"worker_pid": int(pid)}
                return {"accepted": True, "pid": int(pid)}
            finally:
                _close(thread)
                _close(process)

    def launch(self, session: Session, target: str, args: str | None, elevated: bool) -> dict:
        payload = base64.urlsafe_b64encode(
            json.dumps({"target": target, "args": args}, ensure_ascii=False).encode("utf-8")
        ).decode("ascii")
        return self._create_user_process(
            session, self.service_exe, ["--user-launch", payload], elevated=elevated,
            wait_for_worker=True,
        )

    def startup(self, session: Session) -> dict:
        app_path = ntpath.normcase(str(self.app_exe))
        for process in self.processes(session):
            if ntpath.normcase(str(process.path)) == app_path:
                return {"accepted": True, "pid": process.pid, "already_running": True}
        return self._create_user_process(session, self.app_exe, [], elevated=False)

    def processes(self, session: Session) -> list[ProcessIdentity]:
        api = _win32()
        _enable_privileges("SeDebugPrivilege")
        processes = []
        for process in api.psutil.process_iter(["pid"]):
            handle = None
            try:
                handle = api.api.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, process.pid)
                identity = _process_identity(handle, process.pid)
                if (identity.sid, identity.session_id) == (session.owner_sid, session.session_id):
                    processes.append(identity)
            except (OSError, api.error):
                # Protected and exited processes are not usable managed targets.
                continue
            finally:
                _close(handle)
        return processes

    def terminate(self, identity: ProcessIdentity) -> dict:
        api = _win32()
        _enable_privileges("SeDebugPrivilege")
        handle = api.api.OpenProcess(
            _PROCESS_QUERY_LIMITED_INFORMATION | _PROCESS_TERMINATE, False, identity.pid,
        )
        try:
            actual = _process_identity(handle, identity.pid)
            if (
                actual.create_time != identity.create_time
                or actual.sid != identity.sid
                or actual.session_id != identity.session_id
                or ntpath.normcase(str(actual.path)) != ntpath.normcase(str(identity.path))
            ):
                raise PermissionError("The selected process identity has changed.")
            # The verified handle stays open through termination. Never reopen by PID.
            api.process.TerminateProcess(handle, 1)
            return {"accepted": True, "pid": identity.pid}
        finally:
            _close(handle)

    def prepare_power(self, action: str) -> None:
        """Check the requested capability before acknowledging a power command."""
        if action not in {"shutdown", "restart", "sleep"}:
            raise ValueError("Unsupported Windows power action.")
        if action == "sleep" and not _power_capabilities().SystemS3:
            raise NotImplementedError(
                "UnsupportedS3: This host does not support S3 sleep; Modern Standby is not substituted."
            )
        _enable_privileges("SeShutdownPrivilege")

    def power(self, action: str) -> dict:
        self.prepare_power(action)
        if action == "sleep":
            native = ctypes.WinDLL("powrprof", use_last_error=True)
            native.SetSuspendState.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, ctypes.c_ubyte]
            native.SetSuspendState.restype = ctypes.c_ubyte
            success = native.SetSuspendState(False, False, False)
        else:
            native = ctypes.WinDLL("user32", use_last_error=True)
            native.ExitWindowsEx.argtypes = [wintypes.UINT, wintypes.DWORD]
            native.ExitWindowsEx.restype = wintypes.BOOL
            flags = 0x00000008 if action == "shutdown" else 0x00000002
            reason = 0x80040000  # Planned application shutdown, no force flags.
            success = native.ExitWindowsEx(flags, reason)
        if not success:
            raise ctypes.WinError(ctypes.get_last_error())
        return {"accepted": True, "action": action}
