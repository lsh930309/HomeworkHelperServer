"""Privilege invariants with inert effects and a read-only native Windows folder check."""
from dataclasses import dataclass, replace
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.host_service.controller import ProcessIdentity, Session
from src.host_service import windows_backend as native


@pytest.mark.skipif(os.name != "nt", reason="Requires actual Windows Known Folder APIs and registry")
def test_actual_windows_program_files_roots_match_os_paths():
    """Read both native folders without service registration, elevation or filesystem writes."""
    import winreg

    # Match the process architecture, independently of GUID literals in product code.
    registry_view = (winreg.KEY_WOW64_64KEY if native.ctypes.sizeof(native.ctypes.c_void_p) == 8
                     else winreg.KEY_WOW64_32KEY)
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                        r"SOFTWARE\Microsoft\Windows\CurrentVersion",
                        0, winreg.KEY_READ | registry_view) as key:
        program_files = Path(winreg.QueryValueEx(key, "ProgramFilesDir")[0]).resolve(strict=True)
        try:
            program_files_x86 = Path(winreg.QueryValueEx(key, "ProgramFilesDir (x86)")[0]).resolve(strict=True)
        except FileNotFoundError:
            # Windows 32-bit has one Program Files folder for both documented IDs.
            program_files_x86 = program_files
    roots = set(native._program_files_roots())
    assert roots == {program_files, program_files_x86}
    assert all(root.is_dir() and root.is_absolute() for root in roots)


@dataclass
class Token:
    sid: str = "owner"
    session_id: int = 7
    logon_id: str = "logon-42"
    elevated: bool = False
    split: bool = True
    linked: object = None
    closed: bool = False

    def Close(self):
        self.closed = True


@dataclass
class ProcessHandle:
    token: Token
    pid: int = 123
    path: str = r"C:\Program Files\HomeworkHelper\homework_helper.exe"
    created: float = 1234567890.25
    closed: bool = False

    def Close(self):
        self.closed = True


class Security:
    TokenUser, TokenSessionId, TokenStatistics = range(3)
    TokenElevation, TokenElevationType, TokenLinkedToken = range(3, 6)
    TokenElevationTypeDefault = 1
    SecurityImpersonation, TOKEN_ALL_ACCESS, TokenPrimary = 2, 0xFFFF, 1

    def __init__(self, harness):
        self.harness = harness
        self.duplicates = []
        self.impersonated = None
        self.reverted = 0
        self.opened_tokens = []

    def GetTokenInformation(self, token, kind):
        if kind == self.TokenLinkedToken:
            if token.linked is None:
                raise OSError("no linked token")
            return token.linked
        return {
            self.TokenUser: (token.sid, 0),
            self.TokenSessionId: token.session_id,
            self.TokenStatistics: {"AuthenticationId": token.logon_id},
            self.TokenElevation: token.elevated,
            self.TokenElevationType: 3 if token.split else self.TokenElevationTypeDefault,
        }[kind]

    def ConvertSidToStringSid(self, sid):
        return sid

    def DuplicateTokenEx(self, token, impersonation, access, token_type):
        assert token_type == self.TokenPrimary
        result = replace(token, linked=None, closed=False)
        self.duplicates.append(result)
        return result

    def OpenThreadToken(self, thread, access, as_self):
        token = replace(self.harness.pipe_token, closed=False)
        self.opened_tokens.append(token)
        return token

    def OpenProcessToken(self, handle, access):
        assert not handle.closed
        token = replace(handle.token, closed=False)
        self.opened_tokens.append(token)
        return token

    def ImpersonateLoggedOnUser(self, token):
        self.impersonated = token

    def RevertToSelf(self):
        self.impersonated = None
        self.reverted += 1


class Harness:
    def __init__(self):
        self.user_token = Token()
        self.pipe_token = Token()
        self.handle = ProcessHandle(Token())
        self.security = Security(self)
        self.opened_handles = []
        self.terminated = []
        self.api = SimpleNamespace(
            security=self.security,
            ts=SimpleNamespace(WTSQueryUserToken=lambda session: self.user_token),
            api=SimpleNamespace(OpenProcess=self.open_process, GetCurrentThread=lambda: -2),
            pipe=SimpleNamespace(ImpersonateNamedPipeClient=lambda handle: None),
            process=SimpleNamespace(TerminateProcess=self.terminate_process),
            error=OSError,
        )

    def open_process(self, access, inherit, pid):
        assert pid == self.handle.pid
        self.opened_handles.append(self.handle)
        return self.handle

    def terminate_process(self, handle, code):
        assert not handle.closed
        self.terminated.append(handle)

    def pipe_client_pid(self, handle, result):
        result._obj.value = self.handle.pid
        return True


@pytest.fixture
def backend(monkeypatch, tmp_path):
    harness = Harness()
    monkeypatch.setattr(native, "_win32", lambda: harness.api)
    monkeypatch.setattr(native, "_enable_privileges", lambda *names: None)
    monkeypatch.setattr(native, "_image_path", lambda handle: handle.path)
    monkeypatch.setattr(native, "_creation_time", lambda handle: handle.created)
    monkeypatch.setattr(
        native, "_kernel32",
        lambda: SimpleNamespace(GetNamedPipeClientProcessId=harness.pipe_client_pid),
    )
    return native.WindowsBackend(tmp_path), harness


@pytest.fixture
def session(tmp_path):
    return Session("owner", 7, tmp_path / "HomeworkHelper", "logon-42")


def test_regular_launch_uses_a_non_elevated_user_primary_token(backend, session):
    service, harness = backend
    with service._user_token(session, elevated=False) as token:
        assert not token.elevated
        assert token.sid == session.owner_sid
        assert token is not harness.user_token
    assert token.closed and harness.user_token.closed


def test_admin_launch_uses_linked_user_token_and_never_system(backend, session):
    service, harness = backend
    linked = Token(elevated=True)
    harness.user_token.linked = linked
    with service._user_token(session, elevated=True) as token:
        assert token.elevated
        assert token.sid == "owner"
        assert token.session_id == 7
    assert linked.closed and token.closed and harness.user_token.closed


def test_regular_launch_from_full_token_selects_its_limited_user_token(backend, session):
    service, harness = backend
    harness.user_token = Token(elevated=True, linked=Token())
    with service._user_token(session, elevated=False) as token:
        assert not token.elevated and token.sid == "owner"
    assert harness.user_token.linked.closed


def test_standard_user_cannot_request_an_elevated_token(backend, session):
    service, harness = backend
    harness.user_token = Token(split=False)
    with pytest.raises(PermissionError):
        with service._user_token(session, elevated=True):
            pytest.fail("A standard user must not receive an elevated token")
    assert not harness.security.duplicates
    assert harness.user_token.closed


@pytest.mark.parametrize("changes", [
    {"sid": "different-user"}, {"session_id": 8}, {"logon_id": "new-logon"},
])
def test_stale_or_different_owner_session_cannot_launch(backend, session, changes):
    service, harness = backend
    harness.user_token = replace(harness.user_token, **changes)
    with pytest.raises(PermissionError):
        with service._user_token(session, elevated=False):
            pytest.fail("A stale or different user session must be rejected")
    assert not harness.security.duplicates
    assert harness.user_token.closed


@pytest.mark.parametrize("changes", [{"sid": "S-1-5-18"}, {"session_id": 8}])
def test_linked_token_must_belong_to_the_requested_user_session(backend, session, changes):
    service, harness = backend
    harness.user_token.linked = Token(elevated=True, **changes)
    with pytest.raises(PermissionError):
        with service._user_token(session, elevated=True):
            pytest.fail("A linked token cannot change the owner or session")
    assert harness.user_token.linked.closed
    assert not harness.security.duplicates


def test_profile_reader_restores_service_identity_on_failure(backend, session):
    service, harness = backend
    with pytest.raises(ValueError, match="reader failed"):
        with service.read_as_user(session):
            assert harness.security.impersonated.sid == "owner"
            assert not harness.security.impersonated.elevated
            raise ValueError("reader failed")
    assert harness.security.impersonated is None
    assert harness.security.reverted == 1
    assert all(token.closed for token in harness.security.duplicates)


def identity(handle):
    return ProcessIdentity(handle.pid, handle.created, handle.path,
                           handle.token.sid, handle.token.session_id)


@pytest.mark.parametrize("changes", [
    {"create_time": 1234567890.5}, {"sid": "different-user"},
    {"session_id": 8}, {"path": r"C:\Other\game.exe"},
])
def test_changed_process_identity_is_not_terminated(backend, changes):
    service, harness = backend
    requested = replace(identity(harness.handle), **changes)
    with pytest.raises(PermissionError):
        service.terminate(requested)
    assert harness.terminated == []
    assert harness.handle.closed
    assert len(harness.opened_handles) == 1


def test_termination_uses_the_same_handle_that_was_verified(backend):
    service, harness = backend
    requested = identity(harness.handle)
    result = service.terminate(requested)
    assert result["accepted"] and result["pid"] == requested.pid
    assert harness.terminated == [harness.opened_handles[0]]
    assert harness.handle.closed
    assert len(harness.opened_handles) == 1


def test_pipe_authentication_identifies_actual_process_and_endpoint_token(backend):
    service, harness = backend
    caller = service.authenticate(999)
    assert (caller.pid, caller.sid, caller.session_id, caller.image_path) == (
        123, "owner", 7, harness.handle.path,
    )
    assert harness.security.reverted == 1
    assert harness.handle.closed
    assert all(token.closed for token in harness.security.opened_tokens)


@pytest.mark.parametrize("changes", [
    {"sid": "different-user"}, {"session_id": 8}, {"logon_id": "new-logon"},
])
def test_pipe_endpoint_must_match_the_pid_token_before_authorization(backend, changes):
    service, harness = backend
    harness.pipe_token = replace(harness.pipe_token, **changes)
    with pytest.raises(PermissionError):
        service.authenticate(999)
    assert harness.security.reverted == 1
    assert harness.handle.closed
    assert all(token.closed for token in harness.security.opened_tokens)


class Acl:
    def __init__(self, entries):
        self.entries = entries

    def GetAceCount(self):
        return len(self.entries)

    def GetAce(self, index):
        return self.entries[index]


class Descriptor:
    def __init__(self, owner="S-1-5-32-544", entries=()):
        self.owner = owner
        self.acl = None if entries is None else Acl(entries)

    def GetSecurityDescriptorOwner(self):
        return self.owner

    def GetSecurityDescriptorDacl(self):
        return self.acl


@pytest.fixture
def protected_install(monkeypatch, tmp_path):
    root = tmp_path / "Program Files"
    install = root / "HomeworkHelper"
    runtime = install / "_internal"
    runtime.mkdir(parents=True)
    service_exe = install / "homework_helper_service.exe"
    service_exe.write_bytes(b"inert test executable")
    module = runtime / "controller.pyc"
    module.write_bytes(b"inert test module")
    defaults = Descriptor(entries=[
        ((0, 0), 0x1F01FF, "S-1-5-18"),
        ((0, 0), 0x1F01FF, "S-1-5-32-544"),
        ((0, 0), 0x1200A9, "S-1-5-32-545"),
    ])
    descriptors, inspected = {}, []

    def read_descriptor(path, object_type, information):
        resolved = Path(path).resolve()
        inspected.append(resolved)
        return descriptors.get(resolved, defaults)

    security = SimpleNamespace(
        SE_FILE_OBJECT=1, OWNER_SECURITY_INFORMATION=1, DACL_SECURITY_INFORMATION=4,
        GetNamedSecurityInfo=read_descriptor, ConvertSidToStringSid=lambda sid: sid,
    )
    monkeypatch.setattr(native, "_win32", lambda: SimpleNamespace(security=security))
    monkeypatch.setattr(native, "_program_files_roots", lambda: (root.resolve(),))
    return SimpleNamespace(root=root, install=install, service_exe=service_exe,
                           runtime=runtime, module=module, descriptors=descriptors,
                           inspected=inspected, tmp_path=tmp_path)


def test_protected_program_files_runtime_accepts_normal_read_only_users(protected_install):
    fixture = protected_install
    native.validate_protected_install(fixture.service_exe)
    assert set(fixture.inspected) == {
        fixture.root, fixture.install, fixture.runtime, fixture.service_exe, fixture.module,
    }
    assert fixture.inspected[0] == fixture.root


@pytest.mark.parametrize("location", ["root", "install", "service_exe", "runtime", "module"])
@pytest.mark.parametrize("rights", [
    0x2, 0x4, 0x10, 0x40, 0x100, 0x10000, 0x40000, 0x80000,
    0x40000000, 0x10000000,
])
def test_unprivileged_modification_is_rejected_everywhere_in_runtime_chain(
    protected_install, location, rights,
):
    fixture = protected_install
    fixture.descriptors[getattr(fixture, location)] = Descriptor(
        entries=[((0, 0), rights, "S-1-5-32-545")],
    )
    with pytest.raises(PermissionError, match="ordinary account"):
        native.validate_protected_install(fixture.service_exe)


@pytest.mark.parametrize("owner", ["S-1-5-21-1-2-3-1001", "S-1-5-19", "S-1-5-80-12345"])
def test_user_or_arbitrary_service_owner_cannot_control_system_payload(protected_install, owner):
    fixture = protected_install
    fixture.descriptors[fixture.service_exe] = Descriptor(owner=owner)
    with pytest.raises(PermissionError, match="untrusted owner"):
        native.validate_protected_install(fixture.service_exe)


def test_null_dacl_is_rejected(protected_install):
    fixture = protected_install
    fixture.descriptors[fixture.module] = Descriptor(entries=None)
    with pytest.raises(PermissionError, match="null DACL"):
        native.validate_protected_install(fixture.service_exe)


def test_inherit_only_creator_owner_is_not_an_effective_write_grant(protected_install):
    fixture = protected_install
    fixture.descriptors[fixture.root] = Descriptor(entries=[
        ((0, 0x08), 0x1F01FF, "S-1-3-0"),
    ])
    native.validate_protected_install(fixture.service_exe)


def test_trustedinstaller_owned_runtime_is_supported(protected_install):
    fixture = protected_install
    fixture.descriptors[fixture.module] = Descriptor(
        owner=native._TRUSTED_INSTALLER_SID,
        entries=[((0, 0), 0x1F01FF, native._TRUSTED_INSTALLER_SID)],
    )
    native.validate_protected_install(fixture.service_exe)


def test_object_allow_ace_cannot_hide_unprivileged_write(protected_install):
    fixture = protected_install
    fixture.descriptors[fixture.module] = Descriptor(entries=[
        ((5, 0), 0x2, None, None, "S-1-1-0"),
    ])
    with pytest.raises(PermissionError, match="ordinary account"):
        native.validate_protected_install(fixture.service_exe)


def test_user_directory_portable_service_installation_is_rejected(protected_install):
    fixture = protected_install
    portable = fixture.tmp_path / "Downloads"
    portable.mkdir()
    exe = portable / "homework_helper_service.exe"
    exe.write_bytes(b"inert portable test executable")
    with pytest.raises(PermissionError, match="protected Program Files"):
        native.validate_protected_install(exe)
    assert not fixture.inspected


def test_runtime_reparse_point_cannot_redirect_imports_to_a_user_directory(protected_install, monkeypatch):
    fixture = protected_install
    unsafe = fixture.runtime / "unsafe"
    unsafe.mkdir()
    original = Path.lstat

    def lstat(path, *args, **kwargs):
        result = original(path, *args, **kwargs)
        if path == unsafe:
            return SimpleNamespace(st_mode=result.st_mode, st_file_attributes=0x400)
        return result

    monkeypatch.setattr(Path, "lstat", lstat)
    with pytest.raises(PermissionError, match="reparse points"):
        native.validate_protected_install(fixture.service_exe)


def test_external_alias_to_protected_executable_is_not_a_safe_imagepath(protected_install, monkeypatch):
    fixture = protected_install
    alias = fixture.tmp_path / "user-owned-alias.exe"
    original = Path.resolve

    def resolve(path, *args, **kwargs):
        return fixture.service_exe if path == alias else original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    with pytest.raises(PermissionError, match="protected Program Files"):
        native.validate_protected_install(alias)
    assert not fixture.inspected


def test_launch_timeout_stops_only_the_worker_and_reports_unknown_outcome(backend, session, monkeypatch):
    service, harness = backend
    worker = ProcessHandle(Token(), pid=900)
    thread = Token()
    waited = []
    harness.api.con = SimpleNamespace(CREATE_UNICODE_ENVIRONMENT=0x400, CREATE_NO_WINDOW=0x8000000)
    harness.api.profile = SimpleNamespace(CreateEnvironmentBlock=lambda token, inherit: {"USER": "owner"})
    harness.api.process.STARTUPINFO = lambda: SimpleNamespace()
    harness.api.process.CreateProcessAsUser = lambda *args: (worker, thread, 900, 901)

    def wait(handle, milliseconds):
        waited.append((handle, milliseconds))
        return 258 if milliseconds == 10_000 else 0

    harness.api.event = SimpleNamespace(WaitForSingleObject=wait, WAIT_TIMEOUT=258, WAIT_OBJECT_0=0)
    monkeypatch.setattr(service, "current_session", lambda owner: session)
    with pytest.raises(TimeoutError, match="result is unknown.*Do not retry automatically"):
        service._create_user_process(
            session, service.service_exe, ["--user-launch", "inert"],
            elevated=False, wait_for_worker=True,
        )
    assert harness.terminated == [worker]
    assert waited == [(worker, 10_000), (worker, 2_000)]
    assert worker.closed and thread.closed
    assert harness.handle not in harness.terminated


def test_power_capabilities_structure_matches_windows_abi():
    assert native.ctypes.sizeof(native._PowerCapabilities) == 76
    assert native._PowerCapabilities.SystemS3.offset == 5
    assert native._PowerCapabilities.AoAc.offset == 20


def test_s3_supported_sleep_is_prepared_without_executing_power(backend, monkeypatch):
    service, _harness = backend
    enabled = []
    monkeypatch.setattr(native, "_power_capabilities", lambda: SimpleNamespace(SystemS3=True))
    monkeypatch.setattr(native, "_enable_privileges", lambda *names: enabled.extend(names))
    service.prepare_power("sleep")
    assert enabled == ["SeShutdownPrivilege"]


def test_modern_standby_only_host_rejects_s3_before_any_power_effect(backend, monkeypatch):
    service, _harness = backend
    enabled = []
    monkeypatch.setattr(native, "_power_capabilities", lambda: SimpleNamespace(SystemS3=False, AoAc=True))
    monkeypatch.setattr(native, "_enable_privileges", lambda *names: enabled.extend(names))
    with pytest.raises(NotImplementedError, match="UnsupportedS3"):
        service.prepare_power("sleep")
    with pytest.raises(NotImplementedError, match="UnsupportedS3"):
        service.power("sleep")
    assert enabled == []


def test_power_capability_query_failure_is_not_acknowledged_as_supported(backend, monkeypatch):
    service, _harness = backend

    def query():
        raise OSError("GetPwrCapabilities failed")

    monkeypatch.setattr(native, "_power_capabilities", query)
    with pytest.raises(OSError, match="GetPwrCapabilities failed"):
        service.prepare_power("sleep")


@pytest.mark.parametrize("action", ["shutdown", "restart"])
def test_shutdown_and_restart_preflight_do_not_require_s3(backend, monkeypatch, action):
    service, _harness = backend
    enabled = []

    def unexpected_query():
        pytest.fail("Shutdown/restart must not depend on the sleep hardware capability")

    monkeypatch.setattr(native, "_power_capabilities", unexpected_query)
    monkeypatch.setattr(native, "_enable_privileges", lambda *names: enabled.extend(names))
    service.prepare_power(action)
    assert enabled == ["SeShutdownPrivilege"]
