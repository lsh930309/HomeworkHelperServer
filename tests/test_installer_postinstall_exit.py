"""Exercise production Inno callbacks with isolated test files and inert system actions."""

import codecs
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest


pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="Inno Setup exit codes require actual Windows"
)

INSTALLER = Path(__file__).resolve().parents[1] / "installer.iss"


def _production_callbacks() -> str:
    source = INSTALLER.read_text(encoding="utf-8")
    start = source.index("procedure CurStepChanged(")
    exit_code = source.index("function GetCustomSetupExitCode(", start)
    end = source.index("\nend;", exit_code) + len("\nend;")
    # Copy both callbacks intact; only the operations they call are inert stubs.
    callbacks = source[start:end]
    assert "function GetCustomSetupExitCode(" in callbacks
    globals_source = source[source.index("\nvar\n"):source.index("function ConvertOwnerSid(")]
    declarations = re.findall(r"^\s*[A-Za-z_][A-Za-z_0-9, ]*:\s*Boolean\s*;", globals_source, re.MULTILINE)
    assert declarations, "Use the installer's actual completion declarations"
    return "var\n" + "\n".join(item.strip() for item in declarations) + "\n\n" + callbacks


@pytest.fixture(scope="module")
def inert_setup_exe(tmp_path_factory):
    directory = tmp_path_factory.mktemp("inno postinstall fixture")
    source_path = directory / "fixture.iss"
    # No files, application directory, icons, uninstall registration, services,
    # scheduled tasks, shortcuts, registry actions, or elevated manifest exist.
    source = r"""[Setup]
AppName=HH Inert Postinstall Fixture
AppVersion=1.0
DefaultDirName={tmp}\HH Inert Postinstall Fixture
CreateAppDir=no
Uninstallable=no
CreateUninstallRegKey=no
AllowNoIcons=yes
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableWelcomePage=yes
DisableReadyPage=yes
DisableFinishedPage=yes
PrivilegesRequired=lowest
OutputDir=output
OutputBaseFilename=fixture
Compression=none

[Code]
procedure RecordInertStep(Name: String);
begin
  Log('HH_INERT_STEP:' + Name);
  if ExpandConstant('{param:FailAt|success}') = Name then
    RaiseException('HH_INERT_FAILURE:' + Name);
end;

procedure InstallPrivilegeService();
begin
  RecordInertStep('service');
end;

procedure DeleteScheduledTasks();
begin
  RecordInertStep('tasks');
end;

procedure RemoveLegacyStartupShortcut();
begin
  RecordInertStep('shortcut');
end;

"""
    # Pascal globals precede routines; keep the product callbacks unchanged.
    callbacks = _production_callbacks()
    declaration, callbacks = callbacks.split("\n\n", 1)
    source = source.replace("[Code]\n", "[Code]\n" + declaration + "\n\n") + callbacks
    source_path.write_text(source, encoding="utf-8-sig")
    compiler = Path(os.environ["ProgramFiles(x86)"]) / "Inno Setup 6" / "ISCC.exe"
    assert compiler.is_file(), "Actual Inno Setup compiler is required for this Windows test"
    result = subprocess.run(
        [str(compiler), "/Qp", str(source_path)],
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, repr(result.stdout + result.stderr)
    executable = directory / "output" / "fixture.exe"
    assert executable.is_file()
    return executable


@pytest.mark.parametrize(
    "failure, expected_exit, expected_steps",
    [
        ("success", 0, ["service", "tasks", "shortcut"]),
        ("service", 1, ["service"]),
        ("tasks", 1, ["service", "tasks"]),
        ("shortcut", 1, ["service", "tasks", "shortcut"]),
    ],
)
def test_inno_postinstall_exit_matches_completed_operations(
    tmp_path, inert_setup_exe, failure, expected_exit, expected_steps
):
    log_path = tmp_path / "setup.log"
    result = subprocess.run(
        [
            str(inert_setup_exe), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
            "/SP-", "/NOICONS", f"/LOG={log_path}", f"/FailAt={failure}",
        ],
        capture_output=True,
        timeout=45,
    )
    raw_log = log_path.read_bytes()
    encoding = "utf-16" if raw_log.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)) else "utf-8-sig"
    log = raw_log.decode(encoding)
    observed_steps = re.findall(r"HH_INERT_STEP:([^\r\n]+)", log)
    assert observed_steps == expected_steps, log
    assert result.returncode == expected_exit, log
    if failure != "success":
        assert f"HH_INERT_FAILURE:{failure}" in log, log


def _uninstall_callbacks():
    source = INSTALLER.read_text(encoding="utf-8")

    def between(start, end):
        return source[source.index(start):source.index(end, source.index(start))]

    declarations = between("\nconst\n", "function ConvertOwnerSid(")
    native = between("function OpenDataPath(", "procedure CloseAppNormally(); forward;")
    owner_path = between("function InstalledOwnerProfile(", "function ConfirmAppDataCleanup(")
    owner_path = owner_path.replace("IsInstalledOwner(", "FixtureIsInstalledOwner(").replace(
        "RegQueryStringValue(HKLM64, WindowsProfileList + OwnerSid, 'ProfileImagePath', Profile)",
        "FixtureReadProfile(Profile)",
    ).replace("ExpandConstant('{userappdata}')", "FixtureRoaming()").replace("GetEnv('APPDATA')", "FixtureAppDataEnv()")
    dialog = between("function ConfirmAppDataCleanup(", "function OpenPinnedDataPath(")
    assert dialog.count("Form.ShowModal") == 1
    dialog = dialog.replace("Form.ShowModal", "FixtureCheckboxResult(DeleteCheck)")
    deletion = between("function OpenPinnedDataPath(", "\nfunction RemoveLegacyStartupShortcutForOwner(")
    callback = between("procedure CurUninstallStepChanged(", "function IsProcessRunning(")
    callback = callback.replace(
        "RegQueryStringValue(HKLM64, PrivilegeServiceParameters, 'OwnerSid', OwnerSid);", "FixtureReadOwner(OwnerSid);")
    for operation in ("UninstallSilent", "AppProcessStateForDataCleanup", "CloseAppNormally", "Exec",
                      "DeleteScheduledTasks", "RemoveLegacyStartupShortcutForOwner", "MsgBox"):
        assert re.search(rf"\b{operation}\b", callback), operation
        callback = re.sub(rf"\b{operation}\b", f"Fixture{operation}", callback)
    # A production call left in the fixture could reach the real service or registry.
    assert "FixtureReadOwner(OwnerSid);" in callback and "RegQueryStringValue" not in callback
    assert "RegQueryStringValue" not in owner_path and "FixtureReadProfile(Profile)" in owner_path
    assert "FixtureAppDataEnv()" in owner_path and "FixtureRoaming()" in owner_path
    return declarations + native, owner_path + dialog + deletion + callback


@pytest.fixture(scope="module")
def inert_uninstall_setup_exe(tmp_path_factory):
    directory = tmp_path_factory.mktemp("inno uninstall fixture")
    (directory / "payload.txt").write_text("fixture only", encoding="utf-8")
    source_path = directory / "fixture.iss"
    declarations, callbacks = _uninstall_callbacks()
    test_root = str(tmp_path_factory.getbasetemp()).replace("'", "''")
    declarations = declarations.replace("\nconst\n", f"\nconst\n  FixtureRoot = '{test_root}';\n", 1)
    declarations = declarations.replace("\nvar\n", "\nvar\n  FixtureAppClosed: Boolean;\n", 1)
    source_path.write_text(r'''#define MyAppName "HomeworkHelper"
[Setup]
AppName=HH Inert Uninstall Fixture
AppVersion=1.0
DefaultDirName={tmp}\HH Inert Uninstall Fixture
UsePreviousAppDir=no
CreateUninstallRegKey=no
AllowNoIcons=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=output
OutputBaseFilename=fixture
Compression=none

[Files]
Source: "payload.txt"; DestDir: "{app}"

[Code]
''' + declarations + r'''
function FixtureCase(): String;
begin
  Result := ExpandConstant('{param:FixtureCase|silent}');
end;

function FixtureUninstallSilent(): Boolean;
begin
  Result := UninstallSilent and (FixtureCase() = 'silent');
end;

procedure FixtureReadOwner(var OwnerSid: String);
begin
  OwnerSid := 'S-1-5-21-111-222-333-1001';
  Log('HH_UNINSTALL:owner');
end;

function FixtureIsInstalledOwner(const OwnerSid: String): Boolean;
begin
  Result := (OwnerSid = 'S-1-5-21-111-222-333-1001') and (FixtureCase() <> 'other-owner');
end;

function FixtureReadProfile(var Profile: String): Boolean;
begin
  Profile := AddBackslash(ExtractFileDir(ExpandConstant('{app}'))) + 'owner';
  Result := SameText(ExtractFileDir(ExtractFileDir(Profile)), FixtureRoot);
end;

function FixtureRoaming(): String;
begin
  Result := AddBackslash(ExtractFileDir(ExpandConstant('{app}'))) + 'owner\AppData\Roaming';
end;

function FixtureAppDataEnv(): String;
begin
  Result := FixtureRoaming();
  if FixtureCase() = 'redirected' then Result := Result + '-other';
end;

function FixtureCheckboxResult(Check: TNewCheckBox): Integer;
begin
  if Check.Checked then RaiseException('삭제 체크박스가 기본 선택됨');
  Log('HH_UNINSTALL:unchecked');
  if Check.Enabled then Log('HH_UNINSTALL:checkbox-enabled');
  if Check.Enabled and (FixtureCase() <> 'unchecked') then Check.Checked := True;
  Result := mrOK;
end;

function FixtureAppProcessStateForDataCleanup(): Integer;
begin
  if (FixtureCase() = 'running') or ((FixtureCase() = 'selected') and not FixtureAppClosed) then
    Result := 1
  else
    Result := 0;
end;

procedure FixtureCloseAppNormally();
begin
  FixtureAppClosed := True;
  Log('HH_UNINSTALL:close');
end;

function FixtureExec(const Filename, Params, WorkingDir: String; ShowCmd: Integer;
  Wait: TExecWait; var ResultCode: Integer): Boolean;
begin
  Log('HH_UNINSTALL:service');
  ResultCode := 0;
  Result := True;
end;

procedure FixtureDeleteScheduledTasks();
begin
  Log('HH_UNINSTALL:tasks');
end;

function FixtureRemoveLegacyStartupShortcutForOwner(const OwnerSid: String): TLegacyCleanup;
begin
  if OwnerSid <> 'S-1-5-21-111-222-333-1001' then RaiseException('제거 대상 소유자 변경');
  Log('HH_UNINSTALL:legacy');
  if FixtureCase() = 'legacy-unverified' then Result := lcUnverified else Result := lcDone;
end;

function FixtureMsgBox(const Text: String; Typ: TMsgBoxType; Buttons: Integer): Integer;
begin
  Log('HH_UNINSTALL:preserved:' + Text);
  Result := IDOK;
end;

''' + callbacks, encoding="utf-8-sig")
    compiler = Path(os.environ["ProgramFiles(x86)"]) / "Inno Setup 6" / "ISCC.exe"
    assert compiler.is_file(), "Actual Inno Setup compiler is required for this Windows test"
    result = subprocess.run([str(compiler), "/Qp", str(source_path)], capture_output=True, timeout=60)
    assert result.returncode == 0, repr(result.stdout + result.stderr)
    return directory / "output" / "fixture.exe"


@pytest.mark.parametrize("scenario", [
    "selected", "unchecked", "silent", "other-owner", "redirected", "running", "junction", "parent-junction", "locked",
    "gamebar", "legacy-unverified",
])
def test_inno_uninstall_cleans_only_opted_in_owner_data_without_following_links(tmp_path, inert_uninstall_setup_exe, scenario):
    import ctypes
    from ctypes import wintypes

    owner = tmp_path / "owner"
    roaming = owner / "AppData" / "Roaming"
    data = roaming / "HomeworkHelper"
    db = data / "homework_helper_data" / "app_data.db"
    backup = data / "backups" / "app_data.backup.1.db"
    other = tmp_path / "other" / "AppData" / "Roaming" / "HomeworkHelper" / "other.db"
    outside = tmp_path / "captures" / "shot.png"
    for marker in (db, backup, other, outside):
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(marker.name, encoding="utf-8")

    app = tmp_path / "program"
    result = subprocess.run([str(inert_uninstall_setup_exe), "/VERYSILENT", "/SUPPRESSMSGBOXES",
                             "/NORESTART", "/SP-", f"/DIR={app}"], capture_output=True, timeout=45)
    assert result.returncode == 0, repr(result.stdout + result.stderr)
    assert db.is_file() and backup.is_file()  # Setup must never delete existing user data.
    uninstall, = app.glob("unins*.exe")
    if scenario in {"junction", "parent-junction"}:
        junction, target = data / "outside", outside.parent
        if scenario == "parent-junction":
            junction, target = roaming, tmp_path / "redirected-roaming"
            roaming.rename(target)
        link = subprocess.run(["cmd.exe", "/D", "/C", "mklink", "/J", str(junction), str(target)],
                              capture_output=True, timeout=10)
        assert link.returncode == 0, repr(link.stdout + link.stderr)
    if scenario == "gamebar":
        (data / "display_settings.ini").write_text("[system]\ngamebar_original_value=1\n", encoding="ascii")

    lock = None
    if scenario == "locked":
        native = ctypes.WinDLL("kernel32", use_last_error=True)
        native.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
        native.CreateFileW.restype = wintypes.HANDLE
        native.CloseHandle.argtypes = (wintypes.HANDLE,)
        lock = native.CreateFileW(str(db), 0x80000000, 1, None, 3, 0, None)
        assert lock not in (None, ctypes.c_void_p(-1).value)

    log_path = tmp_path / "uninstall.log"
    try:
        result = subprocess.run([str(uninstall), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                                 f"/LOG={log_path}", f"/FixtureCase={scenario}"], capture_output=True, timeout=45)
    finally:
        if lock is not None:
            assert native.CloseHandle(lock)
    raw = log_path.read_bytes()
    encoding = "utf-16" if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)) else "utf-8-sig"
    log = raw.decode(encoding)
    assert result.returncode == 0, log
    assert not (app / "payload.txt").exists(), log
    events = re.findall(r"HH_UNINSTALL:([a-z-]+)", log)
    assert events[0] == "owner" and events.index("service") < events.index("tasks") < events.index("legacy"), log
    assert ("unchecked" in events) is (scenario != "silent"), log
    assert ("checkbox-enabled" in events) is (scenario not in {"silent", "other-owner", "redirected"}), log
    assert ("close" in events) is (scenario in {"selected", "running"}), log
    preserved = {"running", "junction", "parent-junction", "locked", "gamebar", "legacy-unverified"}
    assert ("preserved" in events) is (scenario in preserved), log
    if scenario == "selected":
        assert not data.exists(), log
    else:
        assert db.read_text(encoding="utf-8") == db.name and backup.read_text(encoding="utf-8") == backup.name, log
    assert other.read_text(encoding="utf-8") == other.name
    assert outside.read_text(encoding="utf-8") == outside.name
