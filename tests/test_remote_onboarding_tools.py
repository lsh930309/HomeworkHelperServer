from pathlib import Path

from src.core.tailscale import TailscalePeer, TailscaleSnapshot, suggest_remote_base_urls
from tools.import_pcremote_power_config import parse_pc_remote_swift


def test_parse_pc_remote_power_constants_into_homeworkhelper_schema():
    source = Path('../pc_remote/Sources/PCRemote/PCRemoteApp.swift').read_text(encoding='utf-8')

    config = parse_pc_remote_swift(source)

    assert config.smartthings_device_id == '145ad447-9969-4ee7-bda0-1760430d9be1'
    assert config.smartthings_cli_path == '/opt/homebrew/bin/smartthings'
    assert config.ssh_host == '211.216.28.65'
    assert config.ssh_port == 50022
    assert config.ssh_user == 'lsh93'
    assert config.ssh_key_path == '~/.ssh/id_ed25519'


def test_tailscale_suggests_http_base_urls_from_online_peer_ipv4s():
    snapshot = TailscaleSnapshot(
        installed=True,
        running=True,
        backend_state='Running',
        self_ips=('100.114.138.46',),
        self_hostname='macbook',
        peers=(
            TailscalePeer('windows-desktop', 'windows-desktop.tail.ts.net.', ('100.109.140.97',), True, 'windows'),
            TailscalePeer('phone', 'phone.tail.ts.net.', ('100.100.100.2',), True, 'android'),
        ),
        message='ok',
    )

    assert suggest_remote_base_urls(snapshot, preferred_names=('windows',)) == ['http://100.109.140.97:8000']


def test_ensure_tailscale_installs_then_rechecks(monkeypatch):
    import src.core.tailscale as tailscale

    before = TailscaleSnapshot(False, False, 'missing', (), '', (), 'missing')
    after = TailscaleSnapshot(True, True, 'Running', ('100.114.138.46',), 'macbook', (), 'ready')
    calls = {'install': 0, 'launch': 0, 'probe': 0}

    def probe():
        calls['probe'] += 1
        return before if calls['probe'] == 1 else after

    def install(runner=None):
        calls['install'] += 1
        return True, 'mock-install'

    def launch(runner=None):
        calls['launch'] += 1
        return True, 'mock-launch'

    monkeypatch.setattr(tailscale, '_install_tailscale', install)
    monkeypatch.setattr(tailscale, '_launch_tailscale', launch)

    result = tailscale.ensure_tailscale_ready(status_probe=probe, retry_delay_seconds=0)

    assert result.ready is True
    assert result.install_attempted is True
    assert result.launch_attempted is True
    assert result.method == 'mock-install+mock-launch'
    assert calls == {'install': 1, 'launch': 1, 'probe': 2}


def test_windows_subprocess_kwargs_hide_console(monkeypatch):
    import src.core.tailscale as tailscale

    class StartupInfo:
        def __init__(self):
            self.dwFlags = 0
            self.wShowWindow = 99

    monkeypatch.setattr(tailscale.platform, 'system', lambda: 'Windows')
    monkeypatch.setattr(tailscale.subprocess, 'STARTUPINFO', StartupInfo, raising=False)
    monkeypatch.setattr(tailscale.subprocess, 'STARTF_USESHOWWINDOW', 1, raising=False)
    monkeypatch.setattr(tailscale.subprocess, 'CREATE_NO_WINDOW', 0x08000000, raising=False)

    kwargs = tailscale._hidden_subprocess_kwargs()

    assert kwargs['creationflags'] == 0x08000000
    assert kwargs['startupinfo'].dwFlags & 1
    assert kwargs['startupinfo'].wShowWindow == 0


def test_windows_tailscale_executable_uses_installed_programfiles_path(monkeypatch):
    import src.core.tailscale as tailscale

    installed = r'C:\Program Files\Tailscale\tailscale.exe'

    monkeypatch.setattr(tailscale.platform, 'system', lambda: 'Windows')
    monkeypatch.setattr(tailscale.shutil, 'which', lambda _name: None)
    monkeypatch.setenv('ProgramFiles', r'C:\Program Files')
    monkeypatch.delenv('ProgramFiles(x86)', raising=False)
    monkeypatch.delenv('LocalAppData', raising=False)
    monkeypatch.setattr(tailscale.Path, 'exists', lambda self: str(self) == installed)

    assert tailscale._tailscale_executable() == installed
    candidates = tailscale._windows_tailscale_candidates()
    assert installed in candidates
    assert r'C:\\Program Files\\Tailscale\\tailscale.exe' not in candidates


def test_tailscale_status_unknown_backend_has_actionable_message(monkeypatch):
    import json
    import src.core.tailscale as tailscale

    class Result:
        returncode = 0
        stdout = json.dumps({'Self': {}, 'Peer': {}})
        stderr = ''

    monkeypatch.setattr(tailscale, '_STATUS_CACHE', None)
    monkeypatch.setattr(tailscale, '_tailscale_executable', lambda: r'C:\Program Files\Tailscale\tailscale.exe')
    monkeypatch.setattr(tailscale.subprocess, 'run', lambda *_args, **_kwargs: Result())

    snapshot = tailscale.tailscale_status()

    assert snapshot.installed is True
    assert snapshot.running is False
    assert snapshot.backend_state == 'unknown'
    assert '로그인/서비스 상태' in snapshot.message


def test_tailscale_status_cache_avoids_repeated_cli_poll(monkeypatch):
    import json
    import src.core.tailscale as tailscale

    class Result:
        returncode = 0
        stdout = json.dumps({'BackendState': 'Running', 'Self': {'TailscaleIPs': ['100.114.138.46']}, 'Peer': {}})
        stderr = ''

    calls = {'run': 0}

    def fake_run(args, **kwargs):
        calls['run'] += 1
        return Result()

    monkeypatch.setattr(tailscale, '_STATUS_CACHE', None)
    monkeypatch.setattr(tailscale, '_tailscale_executable', lambda: '/usr/bin/tailscale')
    monkeypatch.setattr(tailscale.subprocess, 'run', fake_run)

    first = tailscale.tailscale_status(cache_ttl_seconds=30)
    second = tailscale.tailscale_status(cache_ttl_seconds=30)

    assert first.ready is True
    assert second.ready is True
    assert calls['run'] == 1
