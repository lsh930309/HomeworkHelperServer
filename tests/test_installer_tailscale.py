"""Run the installer's actual PowerShell against an inert native CLI on Windows."""

import os
from pathlib import Path
import re
import subprocess
import sys

import pytest


pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="Installer PowerShell requires actual Windows"
)

INSTALLER = Path(__file__).resolve().parents[1] / "installer.iss"


def _bootstrap_script() -> str:
    """Decode only the Pascal literal expression used to write the .ps1 file."""
    source = INSTALLER.read_text(encoding="utf-8")
    procedure = source.split("procedure TryBootstrapTailscalePrerequisite();", 1)[1]
    procedure = procedure.split("procedure DeleteScheduledTasks();", 1)[0]
    expression = re.search(
        r"\bScript\s*:=\s*(.*?)\s*;\s*SaveStringToFile\(",
        procedure,
        re.DOTALL,
    )
    assert expression is not None, "Installer bootstrap must write its generated script"
    literal = expression.group(1)
    pieces = []
    position = 0
    token = re.compile(r"\s+|\+|'(?:[^']|'')*'|#\d+")
    while position < len(literal):
        match = token.match(literal, position)
        assert match is not None, "Bootstrap expression contains a non-literal token"
        part = match.group(0)
        if part.startswith("'"):
            pieces.append(part[1:-1].replace("''", "'"))
        elif part.startswith("#"):
            pieces.append(chr(int(part[1:])))
        position = match.end()
    return "".join(pieces)


@pytest.fixture(scope="module")
def fake_tailscale_exe(tmp_path_factory):
    """An actual .exe exercises Start-Process and native exit codes, not mocks."""
    fixture_dir = tmp_path_factory.mktemp("tailscale native fixture")
    source = fixture_dir / "TailscaleFixture.cs"
    source.write_text(
        r'''
using System;
using System.IO;
using System.Threading;

public static class TailscaleFixture {
    public static int Main(string[] args) {
        string command = String.Join(" ", args);
        File.AppendAllText(Environment.GetEnvironmentVariable("HH_TEST_COMMAND_LOG"),
                          command + Environment.NewLine);
        string scenario = Environment.GetEnvironmentVariable("HH_TEST_SCENARIO");
        if (command == "set --unattended=true") {
            if (scenario == "set_failure") {
                Console.Error.WriteLine("fixture rejected set");
                return 17;
            }
            if (scenario == "timeout") {
                Thread.Sleep(2000);
                File.WriteAllText(Environment.GetEnvironmentVariable("HH_TEST_COMPLETED"),
                                  "native command was not killed");
            }
            return 0;
        }
        if (command == "get --json unattended") {
            Console.WriteLine(scenario == "not_applied"
                ? "{\"unattended\":false}" : "{\"unattended\":true}");
            return 0;
        }
        Console.Error.WriteLine("unexpected fixture arguments: " + command);
        return 23;
    }
}
''',
        encoding="utf-8",
    )
    windows = Path(os.environ["WINDIR"])
    candidates = [
        windows / "Microsoft.NET" / architecture / "v4.0.30319" / "csc.exe"
        for architecture in ("Framework64", "Framework")
    ]
    compiler = next((path for path in candidates if path.is_file()), None)
    assert compiler is not None, "Windows .NET Framework C# compiler is required"
    executable = fixture_dir / "tailscale fixture.exe"
    result = subprocess.run(
        [str(compiler), "/nologo", "/target:exe", f"/out:{executable}", str(source)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert executable.is_file()
    return executable


@pytest.mark.parametrize(
    "scenario, expected_error, expected_commands",
    [
        ("success", None, ["set --unattended=true", "get --json unattended"]),
        ("set_failure", "Tailscale command failed: 17", ["set --unattended=true"]),
        (
            "not_applied",
            "Tailscale unattended setting was not applied",
            ["set --unattended=true", "get --json unattended"],
        ),
        ("timeout", "Tailscale command timed out", ["set --unattended=true"]),
    ],
)
def test_installer_tailscale_native_result(
    tmp_path, fake_tailscale_exe, scenario, expected_error, expected_commands
):
    script = _bootstrap_script()
    # Replace only the two executable discovery arrays. The installer still owns
    # Test-Path, process creation, exit handling, JSON reading, and verification.
    script, replacements = re.subn(
        r"^\$(candidates|exe) = @\(\r?\n.*?^\)",
        lambda match: f"${match.group(1)} = @($env:HH_TEST_TAILSCALE_EXE)",
        script,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert replacements == 2, "Both discovery paths must point only to the fixture"
    if scenario == "timeout":
        script, replacements = re.subn(r"\.WaitForExit\(15000\)", ".WaitForExit(500)", script)
        assert replacements == 1, "Shorten only the native process deadline for this test"

    script_path = tmp_path / "bootstrap.ps1"
    script_path.write_text(script, encoding="utf-8")
    command_log = tmp_path / "commands.txt"
    completed = tmp_path / "completed.txt"
    child_env = os.environ.copy()
    child_env.update(
        HH_TEST_TAILSCALE_EXE=str(fake_tailscale_exe),
        HH_TEST_SCENARIO=scenario,
        HH_TEST_COMMAND_LOG=str(command_log),
        HH_TEST_COMPLETED=str(completed),
        HH_TEST_SCRIPT=str(script_path),
        TEMP=str(tmp_path),
        TMP=str(tmp_path),
    )
    powershell = (
        Path(os.environ["WINDIR"])
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    result = subprocess.run(
        [
            str(powershell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
            "Bypass", "-Command",
            "& { [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false); "
            "$OutputEncoding = [Console]::OutputEncoding; & $env:HH_TEST_SCRIPT }",
        ],
        env=child_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    output = result.stdout + result.stderr
    assert command_log.read_text(encoding="utf-8").splitlines() == expected_commands, output
    if expected_error is None:
        assert result.returncode == 0, output
    else:
        assert result.returncode != 0, output
        assert expected_error in output, output
    if scenario == "timeout":
        assert not completed.exists(), "A timed-out native command must be killed"
    assert not list(tmp_path.glob("*.out")), "Redirected stdout must be cleaned up"
    assert not list(tmp_path.glob("*.err")), "Redirected stderr must be cleaned up"
