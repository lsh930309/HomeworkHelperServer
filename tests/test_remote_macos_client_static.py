from pathlib import Path


MACOS_ROOT = Path("remote_clients/macos/HomeworkHelperRemote")
SOURCE_ROOT = MACOS_ROOT / "Sources/HomeworkHelperRemote"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_macos_package_keeps_native_swiftui_executable_contract():
    package = _read(MACOS_ROOT / "Package.swift")
    app = _read(SOURCE_ROOT / "HomeworkHelperRemoteApp.swift")
    packager = _read(Path("tools/package_macos_remote_app.py"))

    assert 'name: "HomeworkHelperRemote"' in package
    assert 'platforms: [.macOS("26.0")]' in package
    assert '.executableTarget(' in package
    assert 'path: "Sources/HomeworkHelperRemote"' in package
    assert 'import SwiftUI' in app
    assert '@main' in app
    assert 'struct HomeworkHelperRemoteApp: App' in app
    assert '"LSUIElement": True' in packager


def test_macos_models_track_shared_remote_agent_contract():
    models = _read(SOURCE_ROOT / "RemoteModels.swift")

    for model_name in [
        "RemoteStatus",
        "RemoteProcess",
        "RemoteShortcut",
        "RemoteCommandResult",
        "PairingConfirmResponse",
        "RemoteDevice",
        "RemoteDevicesResponse",
        "RemoteCapabilitiesResponse",
        "RemotePowerSetupResponse",
        "RemoteReadiness",
        "RemoteAccessStatus",
        "RemoteLoggingConfigResponse",
    ]:
        assert f"struct {model_name}" in models

    for coding_key in [
        'processLaunch = "process_launch"',
        'processStop = "process_stop"',
        'powerConfig = "power_config"',
        'powerControl = "power_control"',
        'supportedActions = "supported_actions"',
        'targetHost = "target_host"',
        'remoteAccessReadiness = "remote_access_readiness"',
        'publicBaseURL = "public_base_url"',
        'routerRule = "router_rule"',
        'externalPort = "external_port"',
        'internalPort = "internal_port"',
        'tailnetIP = "tailnet_ip"',
        'tokenRefreshedAt = "token_refreshed_at"',
    ]:
        assert coding_key in models


def test_macos_api_client_uses_public_https_and_delegated_power_endpoints():
    client = _read(SOURCE_ROOT / "RemoteAPIClient.swift")

    for endpoint in [
        'remote/status',
        'remote/capabilities',
        'remote/readiness',
        'remote/access/status',
        'remote/processes',
        'remote/processes/\\(pathSegment(id))/launch',
        'remote/processes/\\(pathSegment(id))/stop',
        'remote/pair/confirm',
        'remote/tokens/refresh',
        'remote/devices',
        'remote/power/setup',
        'remote/power/actions/\\(pathSegment(action))',
    ]:
        assert endpoint in client

    for stale in ['remote/tailscale/ensure', 'func ensureServerTailscale']:
        assert stale not in client
    assert 'func executePowerAction(_ action: String) async throws -> RemoteCommandResult' in client
    assert 'request.setValue("Bearer \\(bearerToken)", forHTTPHeaderField: "Authorization")' in client
    assert "private func pathSegment(_ value: String)" in client
    assert 'request.setValue("application/json", forHTTPHeaderField: "Content-Type")' in client
    assert "configuration.waitsForConnectivity = false" in client
    assert 'RemoteAPIError.http(status: http.statusCode, message: "\\(path): \\(message)")' in client


def test_macos_settings_ui_is_public_ip_only_and_hides_legacy_connectivity_controls():
    app = _read(SOURCE_ROOT / "HomeworkHelperRemoteApp.swift")

    for marker in [
        'TextField("공유기 공인 IP", text: $viewModel.routerPublicIPText)',
        'SidebarInfoRow(label: "공개 IP"',
        'TCP 443 → Windows Host 38443',
        'Wake는 Mac 로컬 SmartThings CLI',
        'Host HTTPS Remote Agent',
        'SidebarInfoRow(label: "Wake"',
        'SidebarInfoRow(label: "Host HTTPS"',
        'refreshMoonlightPublicIPViaHTTPS()',
    ]:
        assert marker in app

    for stale in [
        'TextField("Base URL"',
        'TextField("Remote Agent URL"',
        'TextField("SSH host"',
        'TextField("SSH user"',
        'TextField("SSH key path"',
        '서버 Tailscale 확인/복구',
        'Tailscale 선택 fallback',
        'Tailscale 등록 후보',
        'Tailscale Direct로 등록',
        'viewModel.localSSHHealthSummary',
    ]:
        assert stale not in app


def test_macos_viewmodel_normalizes_router_public_ip_and_uses_host_delegated_power():
    view_model = _read(SOURCE_ROOT / "RemoteDashboardViewModel.swift")

    for marker in [
        'normalizePublicRemoteBaseURLText',
        'routerPublicIPInputFromRemoteBaseURL',
        'sanitizeRouterPublicIPInput',
        '@Published var routerPublicIPText',
        'https://\\(trimmed.replacingOccurrences(of: ".", with: "-")).\\(publicRemoteAgentDNSSuffix)',
        'https://\\(ip.replacingOccurrences(of: ".", with: "-")).\\(publicRemoteAgentDNSSuffix)',
        '공유기 WAN IP',
        '공유기 공인 IP가 올바르지 않습니다.',
        'refreshMoonlightPublicIPViaHTTPS()',
        'normalized == "wake"',
        'service.executePowerAction(normalized)',
        'Host HTTPS 위임',
        'Wake는 SmartThings',
        'hostSupportsDelegatedPowerAction',
        'hostDelegatedPowerSummary',
        'beginPowerTransition(for: normalized)',
    ]:
        assert marker in view_model

    for stale in [
        'generateAndSendSSHKey',
        'LocalSSHPowerManager.run',
        'registerMoonlightViaTailscaleDirect',
        'Tailscale 후보를 Base URL로 적용했습니다',
        'ensureServerTailscale',
        'serverTailscaleEnsure',
    ]:
        assert stale not in view_model


def test_macos_keychain_cache_and_supervisor_boundaries_remain_present():
    keychain = _read(SOURCE_ROOT / "KeychainTokenStore.swift")
    cache = _read(SOURCE_ROOT / "RemoteClientCache.swift")
    supervisor = _read(SOURCE_ROOT / "RemoteConnectionSupervisor.swift")

    assert 'struct KeychainTokenStore: RemoteTokenStore' in keychain
    assert 'dev.homeworkhelper.remote' in keychain
    assert 'remote-api-token' in keychain
    assert 'struct RemoteClientCache' in cache
    assert 'RemoteConnectionSupervisor' in supervisor
    for state in ['online', 'offlineExpected', 'agentUnavailable', 'authRejected', 'waking', 'goingOffline', 'restarting']:
        assert state in supervisor
