"""Keep Windows native output separate from our UTF-8 subprocess protocols."""
from types import SimpleNamespace
import platform
import sys

import pytest

from src.core import remote_power_setup


def test_native_acl_probe_keeps_raw_bytes_in_python_utf8_mode(monkeypatch):
    monkeypatch.setenv("PYTHONUTF8", "1")
    monkeypatch.setattr(remote_power_setup.platform, "system", lambda: "Windows")
    observed = []

    def runner(args, **kwargs):
        observed.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout=b"\xb1\xd7\x8f", stderr=b"")

    command = ["icacls", "keys.txt"]
    result = remote_power_setup._run_probe(command, runner=runner)
    args, kwargs = observed[0]
    assert args == command
    assert kwargs["text"] is False
    assert "encoding" not in kwargs
    assert "errors" not in kwargs
    assert result.stdout == b"\xb1\xd7\x8f"


@pytest.mark.parametrize("admin_member", [True, False])
def test_admin_group_identity_comes_from_token_and_includes_deny_only(monkeypatch, admin_member):
    monkeypatch.setattr(remote_power_setup.platform, "system", lambda: "Windows")
    admin_sid = object()
    calls = []
    token = SimpleNamespace(Close=lambda: calls.append("close"))
    monkeypatch.setitem(sys.modules, "win32api", SimpleNamespace(GetCurrentProcess=lambda: "process"))
    monkeypatch.setitem(sys.modules, "win32con", SimpleNamespace(TOKEN_QUERY=8))

    def open_token(process, access):
        assert process == "process" and access == 8
        return token

    security = SimpleNamespace(
        OpenProcessToken=open_token, TokenGroups=2, WinBuiltinAdministratorsSid=26,
        GetTokenInformation=lambda *_args: [(admin_sid, 0x10)] if admin_member else [(object(), 0)],
        CreateWellKnownSid=lambda *_args: admin_sid,
    )
    monkeypatch.setitem(sys.modules, "win32security", security)
    assert remote_power_setup._current_user_is_windows_admin() == (
        admin_member, "Administrators group" if admin_member else "not Administrators group",
    )
    assert calls == ["close"]


def test_owned_powershell_script_and_decoder_share_utf8(monkeypatch):
    monkeypatch.setattr(remote_power_setup.platform, "system", lambda: "Windows")
    observed = []

    def runner(args, **kwargs):
        observed.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="OpenSSH 한글 규칙", stderr="")

    result = remote_power_setup._firewall_status(runner=runner)
    args, kwargs = observed[0]
    assert args[:3] == ["powershell", "-NoProfile", "-Command"]
    assert args[3].startswith("[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); ")
    assert "Get-NetFirewallRule" in args[3]
    assert kwargs["encoding"] == "utf-8"
    assert kwargs["errors"] == "strict"
    assert result["message"] == "OpenSSH 한글 규칙"


@pytest.mark.skipif(platform.system() != "Windows", reason="Windows native CLI output contract")
def test_real_windows_admin_group_query_does_not_depend_on_console_text():
    admin_member, reason = remote_power_setup._current_user_is_windows_admin()
    assert isinstance(admin_member, bool)
    assert reason in {"Administrators group", "not Administrators group"}


@pytest.mark.skipif(platform.system() != "Windows", reason="Windows PowerShell output contract")
def test_real_owned_powershell_script_preserves_korean_output():
    result = remote_power_setup._run_probe(
        ["powershell", "-NoProfile", "-Command", "[Console]::WriteLine('한글 출력 검증')"],
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "한글 출력 검증"


def test_ssh_collector_negotiates_utf8_before_native_output(monkeypatch):
    import shlex
    from pathlib import Path
    from tools import ssh_host_testbench as ssh
    seen=[]
    def run(command, **kwargs):
        script=Path(shlex.split(command)[-1]).read_text(encoding='utf-8')
        assert script.index('[Console]::OutputEncoding') < script.index("Write-Output '한글'")
        assert "$env:PYTHONIOENCODING = 'utf-8'" in script
        assert kwargs['encoding']=='utf-8' and kwargs['errors']=='strict'
        seen.append(script)
        return SimpleNamespace(returncode=0,stdout='한글\n',stderr='')
    monkeypatch.setattr(ssh.subprocess,'run',run)
    result=ssh.run_remote_powershell(ssh.SSHConfig('isolated.invalid',None,22,None), "Write-Output '한글'\n", timeout=1)
    assert result.stdout=='한글\n' and len(seen)==1
