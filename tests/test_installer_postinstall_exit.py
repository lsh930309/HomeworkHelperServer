"""Exercise production Inno callbacks using an installer with no system actions."""

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
    end = source.index("procedure CurUninstallStepChanged(", start)
    # Copy both callbacks intact; only the operations they call are inert stubs.
    callbacks = source[start:end]
    assert "function GetCustomSetupExitCode(" in callbacks
    declaration = re.search(r"^\s*PostInstallSucceeded\s*:\s*Boolean\s*;", source, re.MULTILINE)
    assert declaration is not None, "Use the installer's actual completion flag declaration"
    return "var\n" + declaration.group(0).strip() + "\n\n" + callbacks


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
