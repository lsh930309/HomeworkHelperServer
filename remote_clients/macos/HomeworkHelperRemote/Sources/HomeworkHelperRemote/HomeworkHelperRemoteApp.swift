import SwiftUI

@main
struct HomeworkHelperRemoteApp: App {
    var body: some Scene {
        WindowGroup {
            RemoteDashboardView()
                .frame(minWidth: 1100, minHeight: 680)
        }
        MenuBarExtra("HomeworkHelper", systemImage: "house.circle") {
            Button("대시보드 열기") {
                NSApp.activate(ignoringOtherApps: true)
            }
            Divider()
            Button("종료") { NSApp.terminate(nil) }
        }
    }
}

struct RemoteDashboardView: View {
    @StateObject private var viewModel = RemoteDashboardViewModel()
    @State private var showingAdvancedSettings = false

    var body: some View {
        NavigationSplitView {
            RemoteSidebarView(viewModel: viewModel, showingAdvancedSettings: $showingAdvancedSettings)
                .navigationTitle("HomeworkHelper")
                .navigationSplitViewColumnWidth(min: 260, ideal: 300, max: 340)
        } detail: {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    HeaderStatusView(viewModel: viewModel)

                    GroupBox("게임") {
                        List(viewModel.processes) { process in
                            RemoteProcessRow(process: process) {
                                Task { await viewModel.launch(process) }
                            }
                        }
                        .frame(minHeight: 260)
                    }

                    if let summary = viewModel.dashboardSummary {
                        PlaySummaryView(summary: summary)
                    }

                    if !viewModel.beholderIncidents.isEmpty {
                        BeholderIncidentSummaryView(incidents: viewModel.beholderIncidents)
                    }

                    GroupBox("웹 숏컷") {
                        List(viewModel.shortcuts) { shortcut in
                            HStack {
                                VStack(alignment: .leading) {
                                    Text(shortcut.name).font(.headline)
                                    Text(shortcut.url).font(.caption).foregroundStyle(.secondary)
                                }
                                Spacer()
                                Button("열기") {
                                    Task { await viewModel.open(shortcut) }
                                }
                            }
                        }
                        .frame(minHeight: 160)
                    }
                }
                .padding()
            }
        }
        .sheet(isPresented: $showingAdvancedSettings) {
            AdvancedRemoteSettingsView(viewModel: viewModel)
                .frame(minWidth: 620, minHeight: 720)
        }
        .task { await viewModel.bootstrap() }
    }
}

struct RemoteSidebarView: View {
    @ObservedObject var viewModel: RemoteDashboardViewModel
    @Binding var showingAdvancedSettings: Bool

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                GroupBox("연결") {
                    VStack(alignment: .leading, spacing: 10) {
                        if viewModel.isPaired {
                            SidebarInfoRow(label: "서버", value: viewModel.baseURLText)
                            SidebarInfoRow(label: "디바이스", value: viewModel.deviceName)
                            Text(viewModel.message)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .textSelection(.enabled)
                        } else {
                            TextField("http://windows-tailnet-ip:8000", text: $viewModel.baseURLText)
                                .textFieldStyle(.roundedBorder)
                            TextField("MacBook", text: $viewModel.deviceName)
                                .textFieldStyle(.roundedBorder)
                            HStack {
                                TextField("6자리 페어링 코드", text: $viewModel.pairingCode)
                                    .textFieldStyle(.roundedBorder)
                                Button("페어링") {
                                    Task { await viewModel.confirmPairing() }
                                }
                                .disabled(viewModel.isLoading)
                            }
                            Text("페어링 후에는 토큰/기기 관리 항목을 기본 화면에서 숨깁니다.")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }

                        HStack {
                            Button {
                                Task { await viewModel.refresh() }
                            } label: {
                                Label(viewModel.isLoading ? "연결 중..." : "새로고침", systemImage: "arrow.clockwise")
                            }
                            .disabled(viewModel.isLoading)
                            Button {
                                Task { await viewModel.discoverTailscale() }
                            } label: {
                                Label("탐색", systemImage: "network")
                            }
                            .disabled(viewModel.isLoading)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }

                if let readiness = viewModel.readiness {
                    GroupBox("상태") {
                        VStack(alignment: .leading, spacing: 8) {
                            ReadinessDotRow(title: "Beholder", section: readiness.beholderHealth)
                            ReadinessDotRow(title: "Remote", section: readiness.remoteConnectivity)
                            ReadinessDotRow(title: "Server", section: readiness.serverModeReadiness)
                            ReadinessDotRow(title: "Power", section: readiness.powerReadiness)
                            ReadinessDotRow(title: "Tailscale", section: readiness.tailscaleReadiness)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }

                GroupBox("PC 전원") {
                    VStack(alignment: .leading, spacing: 8) {
                        if viewModel.status?.power?.configured != true {
                            Text("전원 제어 설정 전입니다. 고급 설정에서 최초 1회만 설정하세요.")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        PowerButtonRow(action: "wake", label: "켜기", systemImage: "power", viewModel: viewModel)
                        PowerButtonRow(action: "sleep", label: "절전", systemImage: "moon.fill", viewModel: viewModel)
                        PowerButtonRow(action: "restart", label: "재시작", systemImage: "arrow.clockwise", viewModel: viewModel)
                        PowerButtonRow(action: "shutdown", label: "끄기", systemImage: "power.circle", viewModel: viewModel)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }

                Button {
                    showingAdvancedSettings = true
                } label: {
                    Label("고급 원격 설정", systemImage: "slider.horizontal.3")
                }
                .buttonStyle(.bordered)
            }
            .padding(12)
        }
    }
}

struct HeaderStatusView: View {
    @ObservedObject var viewModel: RemoteDashboardViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("HomeworkHelper Remote")
                .font(.largeTitle.bold())
            Text("게임 실행, 진행률, 전원 제어만 기본 화면에 남기고 페어링/진단 관리는 고급 설정으로 숨겼습니다.")
                .foregroundStyle(.secondary)
            if let readiness = viewModel.readiness {
                HStack {
                    ReadinessPill(title: "Beholder", section: readiness.beholderHealth)
                    ReadinessPill(title: "Remote", section: readiness.remoteConnectivity)
                    ReadinessPill(title: "Server", section: readiness.serverModeReadiness)
                    ReadinessPill(title: "Power", section: readiness.powerReadiness)
                    ReadinessPill(title: "Tailscale", section: readiness.tailscaleReadiness)
                }
            }
        }
    }
}

struct RemoteProcessRow: View {
    let process: RemoteProcess
    let launch: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 6) {
                Text(process.name).font(.headline)
                Text(process.preferredLaunchType ?? "shortcut")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                if let progress = process.progress {
                    GameProgressView(progress: progress)
                }
            }
            Spacer()
            Button("실행", action: launch)
        }
        .padding(.vertical, 4)
    }
}

struct GameProgressView: View {
    let progress: RemoteProcess.Progress

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            ProgressView(value: min(max(progress.percentage, 0), 100), total: 100)
            Text(progress.displayText)
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
    }
}

struct PlaySummaryView: View {
    let summary: RemoteDashboardSummary

    var body: some View {
        GroupBox("플레이 요약") {
            VStack(alignment: .leading, spacing: 8) {
                Text("\(summary.range.start) ~ \(summary.range.end)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                HStack {
                    SummaryMetric(label: "총 플레이", value: formatDuration(summary.metrics.totalSeconds))
                    SummaryMetric(label: "일평균", value: formatDuration(summary.metrics.dailyAverageSeconds))
                    SummaryMetric(label: "세션", value: "\(summary.metrics.sessionCount)")
                    SummaryMetric(label: "플레이 일수", value: "\(summary.metrics.playedDays)")
                }
                if let topGame = summary.metrics.topGame {
                    Text("Top: \(topGame.displayName) · \(formatDuration(topGame.totalSeconds)) · \(topGame.sessionCount)회")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                if let mobile = summary.mobileMetrics {
                    Divider()
                    HStack {
                        SummaryMetric(label: "모바일 플레이", value: formatDuration(mobile.totalSeconds))
                        SummaryMetric(label: "모바일 세션", value: "\(mobile.sessionCount)")
                        SummaryMetric(label: "활성 모바일", value: "\(mobile.activeSessionCount)")
                    }
                    if let topMobileGame = mobile.topGame {
                        Text("Mobile Top: \(topMobileGame.displayName) · \(topMobileGame.androidPackageName) · \(formatDuration(topMobileGame.totalSeconds))")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

struct BeholderIncidentSummaryView: View {
    let incidents: [RemoteBeholderIncident]

    var body: some View {
        GroupBox("Beholder 알림") {
            VStack(alignment: .leading, spacing: 8) {
                ForEach(incidents.prefix(3)) { incident in
                    VStack(alignment: .leading, spacing: 4) {
                        Text(incident.userTitle).font(.headline)
                        Text("위험도 \(incident.riskScore) · \(incident.severity)")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        if let summary = incident.userSummary, !summary.isEmpty {
                            Text(summary)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                    Divider()
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

struct AdvancedRemoteSettingsView: View {
    @ObservedObject var viewModel: RemoteDashboardViewModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                GroupBox("페어링/접속") {
                    VStack(alignment: .leading, spacing: 8) {
                        TextField("Base URL", text: $viewModel.baseURLText)
                            .textFieldStyle(.roundedBorder)
                        SecureField("Bearer token", text: $viewModel.tokenText)
                            .textFieldStyle(.roundedBorder)
                        TextField("디바이스 이름", text: $viewModel.deviceName)
                            .textFieldStyle(.roundedBorder)
                        HStack {
                            TextField("6자리 코드", text: $viewModel.pairingCode)
                                .textFieldStyle(.roundedBorder)
                            Button("페어링 및 자동 설정") {
                                Task { await viewModel.confirmPairing() }
                            }
                            .disabled(viewModel.isLoading)
                        }
                        HStack {
                            Button("자동 설정 점검") { Task { await viewModel.runSetupAutomation() } }
                            Button("서버 Tailscale 확인/복구") { Task { await viewModel.ensureServerTailscale() } }
                                .disabled(viewModel.isLoading || !viewModel.isPaired)
                            Button("페어링 토큰 복구") { Task { await viewModel.recoverPairing() } }
                                .disabled(viewModel.isLoading || !viewModel.isPaired)
                            Button(role: .destructive) { viewModel.clearLocalPairing() } label: { Text("로컬 토큰 삭제") }
                                .disabled(viewModel.isLoading || !viewModel.isPaired)
                        }
                        Toggle("원격 진단 로그를 바탕 화면에 저장", isOn: Binding(
                            get: { viewModel.remoteDesktopLoggingEnabled },
                            set: { enabled in Task { await viewModel.saveRemoteDesktopLogging(enabled: enabled) } }
                        ))
                        Text(viewModel.setupProgress)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .textSelection(.enabled)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }

                GroupBox("Tailscale") {
                    VStack(alignment: .leading, spacing: 8) {
                        Button("Tailscale 찾기") { Task { await viewModel.discoverTailscale() } }
                        if let local = viewModel.localTailscale {
                            SidebarInfoRow(label: "로컬 상태", value: local.message)
                            if !local.selfIPs.isEmpty {
                                SidebarInfoRow(label: "이 Mac", value: local.selfIPs.joined(separator: ", "))
                            }
                            ForEach(local.suggestedBaseURLs, id: \.self) { url in
                                Button(url) { viewModel.applySuggestedBaseURL(url) }
                                    .buttonStyle(.borderless)
                            }
                        }
                        if let serverTailscale = viewModel.serverTailscaleEnsure {
                            SidebarInfoRow(label: "서버 Tailscale", value: serverTailscale.message)
                            SidebarInfoRow(label: "서버 IP", value: serverTailscale.after.selfIPs.isEmpty ? "없음" : serverTailscale.after.selfIPs.joined(separator: ", "))
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }

                GroupBox("전원 설정") {
                    VStack(alignment: .leading, spacing: 8) {
                        if let response = viewModel.powerConfigResponse {
                            SidebarInfoRow(label: "설정 파일", value: response.configPath)
                            SidebarInfoRow(label: "저장 상태", value: response.configExists ? "있음" : "없음")
                            SidebarInfoRow(label: "지원 명령", value: response.readiness.supportedActions.isEmpty ? "없음" : response.readiness.supportedActions.joined(separator: ", "))
                        }
                        TextField("SmartThings device id", text: $viewModel.powerConfig.smartthingsDeviceID)
                            .textFieldStyle(.roundedBorder)
                        TextField("SmartThings CLI path", text: $viewModel.powerConfig.smartthingsCLIPath)
                            .textFieldStyle(.roundedBorder)
                        TextField("SSH host", text: $viewModel.powerConfig.sshHost)
                            .textFieldStyle(.roundedBorder)
                        TextField("SSH user", text: $viewModel.powerConfig.sshUser)
                            .textFieldStyle(.roundedBorder)
                        TextField("SSH key path", text: $viewModel.powerConfig.sshKeyPath)
                            .textFieldStyle(.roundedBorder)
                        Stepper("SSH port: \(viewModel.powerConfig.sshPort)", value: $viewModel.powerConfig.sshPort, in: 1...65535)
                        HStack {
                            Button("SSH host 채우기") { viewModel.applySuggestedPowerHost() }
                            Button("준비 상태 확인") { Task { await viewModel.refreshPowerSetup() } }
                            Button("SSH key 생성/전송") { Task { await viewModel.generateAndSendSSHKey() } }
                                .disabled(!viewModel.isPaired || viewModel.isLoading)
                            Button("SmartThings 기기 확인") { Task { await viewModel.probeSmartThingsDevices() } }
                            Button("전원 설정 저장") { Task { await viewModel.savePowerConfig() } }
                        }
                        if let setup = viewModel.powerSetup {
                            SetupInstructionBlock(
                                title: "Windows 전원 준비",
                                lines: [
                                    "OpenSSH: \(setup.sshService.running ? "실행 중" : "조치 필요")",
                                    "Firewall: \(setup.firewall.enabled ? "SSH 허용" : "확인 필요")",
                                    "authorized_keys: \(setup.authorizedKeysPath)",
                                    "SmartThings CLI: \(setup.smartthingsCLICandidates.first ?? "감지 안 됨")"
                                ]
                            )
                        }
                        if let key = viewModel.localSSHKey {
                            SidebarInfoRow(label: "로컬 SSH key", value: "\(key.privateKeyPath) · \(key.created ? "새로 생성" : "기존 사용")")
                        }
                        if !viewModel.smartThingsDeviceCandidates.isEmpty {
                            Text("SmartThings device 후보").font(.caption.bold())
                            ForEach(viewModel.smartThingsDeviceCandidates.prefix(5)) { candidate in
                                Button("\(candidate.name) · \(candidate.id)") {
                                    viewModel.applySmartThingsDevice(candidate)
                                }
                                .buttonStyle(.borderless)
                            }
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }

                GroupBox("기기 관리") {
                    VStack(alignment: .leading, spacing: 8) {
                        HStack {
                            Button("디바이스 새로고침") { Task { await viewModel.refreshDevices() } }
                                .disabled(viewModel.tokenText.isEmpty || viewModel.isLoading)
                            Button("폐기된 기기 정리") { Task { await viewModel.purgeRevokedDevices() } }
                                .disabled(viewModel.tokenText.isEmpty || viewModel.isLoading)
                            Button("현재 토큰 갱신") { Task { await viewModel.refreshToken() } }
                                .disabled(viewModel.tokenText.isEmpty || viewModel.isLoading)
                        }
                        ForEach(viewModel.devices) { device in
                            HStack {
                                VStack(alignment: .leading) {
                                    Text(device.name)
                                    Text(device.platform ?? "unknown")
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                                Spacer()
                                if device.revokedAt == nil {
                                    Button("폐기") { Task { await viewModel.revoke(device) } }
                                        .buttonStyle(.borderless)
                                } else {
                                    Text("폐기됨").font(.caption).foregroundStyle(.secondary)
                                }
                            }
                            Divider()
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }

                GroupBox("Android-PC 연결") {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Android 클라이언트가 준비될 때 사용할 매핑입니다. 기본 화면에서는 숨깁니다.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        HStack {
                            TextField("PC process ID", text: $viewModel.gameLinkProcessID)
                                .textFieldStyle(.roundedBorder)
                            TextField("Android package", text: $viewModel.gameLinkAndroidPackage)
                                .textFieldStyle(.roundedBorder)
                            Button("연결 저장") { Task { await viewModel.createGameLink() } }
                                .disabled(viewModel.gameLinkProcessID.isEmpty || viewModel.gameLinkAndroidPackage.isEmpty)
                        }
                        ForEach(viewModel.gameLinks) { link in
                            HStack {
                                VStack(alignment: .leading, spacing: 4) {
                                    Text(link.pcDisplayName ?? link.pcProcessID).font(.headline)
                                    Text(link.androidPackageName).font(.caption).foregroundStyle(.secondary)
                                }
                                Spacer()
                                if let session = viewModel.activeMobileSession(for: link) {
                                    Button("모바일 종료") { Task { await viewModel.endMobileSession(session) } }
                                } else {
                                    Button("모바일 시작") { Task { await viewModel.startMobileSession(link) } }
                                }
                            }
                            Divider()
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            .padding()
        }
    }
}

private func formatDuration(_ seconds: Double) -> String {
    let minutes = Int(seconds / 60)
    if minutes < 60 {
        return "\(minutes)분"
    }
    let hours = minutes / 60
    let remainder = minutes % 60
    return remainder == 0 ? "\(hours)시간" : "\(hours)시간 \(remainder)분"
}

struct SummaryMetric: View {
    let label: String
    let value: String

    var body: some View {
        VStack(alignment: .leading) {
            Text(label)
                .font(.caption)
                .foregroundStyle(.secondary)
            Text(value)
                .font(.headline)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct SidebarInfoRow: View {
    let label: String
    let value: String

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label)
                .font(.caption2)
                .foregroundStyle(.secondary)
            Text(value)
                .font(.caption)
                .textSelection(.enabled)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct PowerButtonRow: View {
    let action: String
    let label: String
    let systemImage: String
    @ObservedObject var viewModel: RemoteDashboardViewModel

    var body: some View {
        Button {
            Task { await viewModel.power(action) }
        } label: {
            Label(label, systemImage: systemImage)
        }
        .disabled(viewModel.isLoading || !viewModel.isPowerActionEnabled(action))
    }
}



struct SetupInstructionBlock: View {
    let title: String
    let lines: [String]

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(.caption.bold())
            ForEach(lines, id: \.self) { line in
                Text("• \(line)")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 8))
    }
}

struct SetupChecklistRow: View {
    let title: String
    let detail: String
    let ready: Bool

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: ready ? "checkmark.circle.fill" : "circle")
                .foregroundStyle(ready ? .green : .secondary)
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.caption.bold())
                Text(detail)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct ReadinessDotRow: View {
    let title: String
    let section: RemoteReadiness.Section

    var body: some View {
        HStack(spacing: 8) {
            Circle()
                .fill(readinessColor(section.color))
                .frame(width: 9, height: 9)
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.caption.bold())
                Text(section.message)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct ReadinessPill: View {
    let title: String
    let section: RemoteReadiness.Section

    var body: some View {
        HStack(spacing: 6) {
            Circle().fill(readinessColor(section.color)).frame(width: 8, height: 8)
            Text(title)
                .font(.caption.bold())
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(.thinMaterial, in: Capsule())
        .help(section.message)
    }
}

private func readinessColor(_ color: String) -> Color {
    switch color {
    case "green": return .green
    case "yellow": return .yellow
    case "red": return .red
    default: return .gray
    }
}
