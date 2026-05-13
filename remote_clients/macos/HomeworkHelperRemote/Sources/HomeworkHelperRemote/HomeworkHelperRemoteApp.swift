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

    var body: some View {
        NavigationSplitView {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    GroupBox("Remote Agent") {
                        VStack(alignment: .leading, spacing: 10) {
                            VStack(alignment: .leading, spacing: 6) {
                                Text("Base URL")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                TextField("http://windows-host-or-tailnet-ip:8000", text: $viewModel.baseURLText)
                                    .textFieldStyle(.roundedBorder)
                            }
                            VStack(alignment: .leading, spacing: 6) {
                                Text("Bearer token (선택)")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                SecureField("페어링 후 Keychain에 저장됩니다", text: $viewModel.tokenText)
                                    .textFieldStyle(.roundedBorder)
                            }
                            VStack(alignment: .leading, spacing: 6) {
                                Text("디바이스 이름")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                TextField("MacBook", text: $viewModel.deviceName)
                                    .textFieldStyle(.roundedBorder)
                            }
                            VStack(alignment: .leading, spacing: 6) {
                                Text("페어링 코드")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                HStack {
                                    TextField("6자리 코드", text: $viewModel.pairingCode)
                                        .textFieldStyle(.roundedBorder)
                                    Button("페어링") {
                                        Task { await viewModel.confirmPairing() }
                                    }
                                    .disabled(viewModel.isLoading)
                                }
                            }
                            HStack {
                                Button {
                                    Task { await viewModel.discoverTailscale() }
                                } label: {
                                    Label("Tailscale 찾기", systemImage: "network")
                                }
                                .disabled(viewModel.isLoading)
                                Button {
                                    Task { await viewModel.refresh() }
                                } label: {
                                    Label(viewModel.isLoading ? "연결 중..." : "새로고침", systemImage: "arrow.clockwise")
                                }
                                .disabled(viewModel.isLoading)
                                Spacer()
                            }
                            Text(viewModel.message)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .textSelection(.enabled)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }

                    GroupBox("원격 설정 자동화") {
                        VStack(alignment: .leading, spacing: 10) {
                            Text("Windows 앱의 [설정 > 원격 설정]과 맞물려 Mac Tailscale, 서버 연결, 페어링, 전원 설정을 순서대로 점검합니다.")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            SetupInstructionBlock(
                                title: "Windows에서 먼저",
                                lines: ["HomeworkHelper 실행", "설정 > 원격 설정에서 서버 모드 활성화", "페어링 코드 발급"]
                            )
                            SetupInstructionBlock(
                                title: "이 Mac에서",
                                lines: ["자동 설정 점검 실행", "코드 입력 후 페어링", "전원 설정 저장 및 테스트"]
                            )
                            ForEach(Array(viewModel.setupChecklist.enumerated()), id: \.offset) { _, item in
                                SetupChecklistRow(title: item.0, detail: item.1, ready: item.2)
                            }
                            HStack {
                                Button {
                                    Task { await viewModel.runSetupAutomation() }
                                } label: {
                                    Label("자동 설정 점검", systemImage: "wand.and.stars")
                                }
                                .disabled(viewModel.isLoading)
                                Button {
                                    Task { await viewModel.ensureServerTailscale() }
                                } label: {
                                    Label("서버 Tailscale 확인/복구", systemImage: "network.badge.shield.half.filled")
                                }
                                .disabled(viewModel.isLoading || !viewModel.isPaired)
                            }
                            HStack {
                                Button {
                                    Task { await viewModel.recoverPairing() }
                                } label: {
                                    Label("페어링 토큰 복구", systemImage: "key.fill")
                                }
                                .disabled(viewModel.isLoading || !viewModel.isPaired)
                                Button(role: .destructive) {
                                    viewModel.clearLocalPairing()
                                } label: {
                                    Label("로컬 토큰 삭제", systemImage: "trash")
                                }
                                .disabled(viewModel.isLoading || !viewModel.isPaired)
                            }
                            Text(viewModel.setupProgress)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .textSelection(.enabled)
                            if let serverTailscale = viewModel.serverTailscaleEnsure {
                                SidebarInfoRow(label: "서버 Tailscale", value: serverTailscale.message)
                                SidebarInfoRow(label: "서버 IP", value: serverTailscale.after.selfIPs.isEmpty ? "없음" : serverTailscale.after.selfIPs.joined(separator: ", "))
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }

                    GroupBox("Tailscale") {
                        VStack(alignment: .leading, spacing: 8) {
                            if let local = viewModel.localTailscale {
                                SidebarInfoRow(label: "로컬 상태", value: local.message)
                                if !local.selfIPs.isEmpty {
                                    SidebarInfoRow(label: "이 Mac", value: local.selfIPs.joined(separator: ", "))
                                }
                                let suggestions = local.suggestedBaseURLs
                                if !suggestions.isEmpty {
                                    Text("Windows Desktop 후보")
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                    ForEach(suggestions, id: \.self) { url in
                                        Button(url) { viewModel.applySuggestedBaseURL(url) }
                                            .buttonStyle(.borderless)
                                    }
                                }
                            } else {
                                Text("tailscale CLI로 Windows Desktop tailnet IP를 자동 탐색합니다. 실패하면 Base URL 수동 입력을 계속 사용할 수 있습니다.")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }

                    if let status = viewModel.status {
                        GroupBox("상태") {
                            VStack(alignment: .leading, spacing: 8) {
                                if let readiness = viewModel.readiness {
                                    ReadinessDotRow(title: "Beholder", section: readiness.beholderHealth)
                                    ReadinessDotRow(title: "Remote", section: readiness.remoteConnectivity)
                                    ReadinessDotRow(title: "Server", section: readiness.serverModeReadiness)
                                    ReadinessDotRow(title: "Power", section: readiness.powerReadiness)
                                    ReadinessDotRow(title: "Tailscale", section: readiness.tailscaleReadiness)
                                    Divider()
                                }

                                SidebarInfoRow(label: "API", value: status.remoteAPIVersion)
                                SidebarInfoRow(label: "게임", value: "\(status.counts.processes)")
                                SidebarInfoRow(label: "숏컷", value: "\(status.counts.shortcuts)")
                                SidebarInfoRow(label: "대시보드 요약", value: status.capabilities.dashboardSummary ? "사용 가능" : "미지원")
                                SidebarInfoRow(label: "Beholder", value: status.capabilities.beholderIncidents ? "\(viewModel.beholderIncidents.count)건" : "미지원")
                                SidebarInfoRow(label: "Android-PC 연결", value: status.capabilities.gameLinks ? "\(viewModel.gameLinks.count)개" : "미지원")
                                SidebarInfoRow(label: "모바일 세션", value: status.capabilities.mobileSessions ? "\(viewModel.mobileSessions.count)개" : "미지원")
                                SidebarInfoRow(label: "전원 제어", value: status.capabilities.powerControl ? "설정됨" : "미설정")
                                if let power = status.power {
                                    SidebarInfoRow(label: "전원 상태", value: power.status ?? "unknown")
                                    SidebarInfoRow(label: "지원 명령", value: power.supportedActions.isEmpty ? "없음" : power.supportedActions.joined(separator: ", "))
                                    if let targetHost = power.targetHost, !targetHost.isEmpty {
                                        SidebarInfoRow(label: "대상", value: targetHost)
                                    }
                                }
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                        }

                        GroupBox("PC 전원") {
                            VStack(alignment: .leading, spacing: 8) {
                                if !status.capabilities.powerControl || status.power?.configured != true {
                                    Text("Remote Agent의 전원 제어 adapter가 설정되지 않아 전원 버튼을 비활성화했습니다.")
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

                        GroupBox("전원 설정") {
                            VStack(alignment: .leading, spacing: 8) {
                                if let response = viewModel.powerConfigResponse {
                                    SidebarInfoRow(label: "설정 파일", value: response.configPath)
                                    SidebarInfoRow(label: "저장 상태", value: response.configExists ? "있음" : "없음")
                                    SidebarInfoRow(label: "지원 명령", value: response.readiness.supportedActions.isEmpty ? "없음" : response.readiness.supportedActions.joined(separator: ", "))
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
                                    Button("SSH host 채우기") {
                                        viewModel.applySuggestedPowerHost()
                                    }
                                    Button("준비 상태 확인") {
                                        Task { await viewModel.refreshPowerSetup() }
                                    }
                                    Button("SSH key 생성/전송") {
                                        Task { await viewModel.generateAndSendSSHKey() }
                                    }
                                    .disabled(!viewModel.isPaired || viewModel.isLoading)
                                }
                                HStack {
                                    Button("SmartThings 기기 확인") {
                                        Task { await viewModel.probeSmartThingsDevices() }
                                    }
                                    Button("전원 설정 저장") {
                                        Task { await viewModel.savePowerConfig() }
                                    }
                                }
                                if let key = viewModel.localSSHKey {
                                    SidebarInfoRow(label: "로컬 SSH key", value: "\(key.privateKeyPath) · \(key.created ? "새로 생성" : "기존 사용")")
                                }
                                if !viewModel.smartThingsDeviceCandidates.isEmpty {
                                    Text("SmartThings device 후보")
                                        .font(.caption.bold())
                                    ForEach(viewModel.smartThingsDeviceCandidates.prefix(5)) { candidate in
                                        Button {
                                            viewModel.applySmartThingsDevice(candidate)
                                        } label: {
                                            Text("\(candidate.name) · \(candidate.id)")
                                                .font(.caption2)
                                        }
                                        .buttonStyle(.borderless)
                                    }
                                } else if !viewModel.smartThingsDevices.isEmpty {
                                    Text("SmartThings devices")
                                        .font(.caption.bold())
                                    ForEach(viewModel.smartThingsDevices.prefix(5), id: \.self) { device in
                                        Text(device)
                                            .font(.caption2)
                                            .foregroundStyle(.secondary)
                                            .textSelection(.enabled)
                                    }
                                }
                                Text("저장은 고정된 remote_power_config.json만 갱신하며 전원 명령은 실행하지 않습니다. OpenSSH 설치/방화벽 변경은 Windows에서 명시적으로 승인해야 합니다.")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                        }

                        GroupBox("등록 디바이스") {
                            VStack(alignment: .leading, spacing: 8) {
                                HStack {
                                    Button {
                                        Task { await viewModel.refreshDevices() }
                                    } label: {
                                        Label("디바이스 새로고침", systemImage: "person.2")
                                    }
                                    .disabled(viewModel.tokenText.isEmpty || viewModel.isLoading)
                                    Button {
                                        Task { await viewModel.refreshToken() }
                                    } label: {
                                        Label("현재 토큰 갱신", systemImage: "arrow.triangle.2.circlepath")
                                    }
                                    .disabled(viewModel.tokenText.isEmpty || viewModel.isLoading)
                                }
                                ForEach(viewModel.devices) { device in
                                    HStack {
                                        VStack(alignment: .leading) {
                                            Text(device.name)
                                            Text(device.platform ?? "unknown")
                                                .font(.caption)
                                                .foregroundStyle(.secondary)
                                            if let tokenRefreshedAt = device.tokenRefreshedAt {
                                                Text("refreshed: \(tokenRefreshedAt, specifier: "%.0f")")
                                                    .font(.caption2)
                                                    .foregroundStyle(.secondary)
                                            }
                                        }
                                        Spacer()
                                        if device.revokedAt == nil {
                                            Button("폐기") {
                                                Task { await viewModel.revoke(device) }
                                            }
                                            .buttonStyle(.borderless)
                                        } else {
                                            Text("폐기됨")
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
                .padding(12)
            }
            .navigationTitle("HomeworkHelper")
            .navigationSplitViewColumnWidth(min: 360, ideal: 420, max: 520)
        } detail: {
            VStack(alignment: .leading, spacing: 16) {
                VStack(alignment: .leading, spacing: 10) {
                    Text("HomeworkHelper Remote")
                        .font(.largeTitle.bold())
                    Text("Windows HomeworkHelper 서버와 페어링해 게임 실행, 전원 제어, 플레이 요약을 한 화면에서 확인합니다.")
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

                GroupBox("게임 실행") {
                    List(viewModel.processes) { process in
                        HStack {
                            VStack(alignment: .leading) {
                                Text(process.name).font(.headline)
                                Text(process.preferredLaunchType ?? "shortcut")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                            Spacer()
                            Button("실행") {
                                Task { await viewModel.launch(process) }
                            }
                        }
                    }
                    .frame(minHeight: 220)
                }

                if let summary = viewModel.dashboardSummary {
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

                if !viewModel.beholderIncidents.isEmpty {
                    GroupBox("Beholder 알림") {
                        VStack(alignment: .leading, spacing: 8) {
                            ForEach(viewModel.beholderIncidents.prefix(3)) { incident in
                                VStack(alignment: .leading, spacing: 4) {
                                    Text(incident.userTitle)
                                        .font(.headline)
                                    Text("위험도 \(incident.riskScore) · \(incident.severity)")
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                    if let summary = incident.userSummary, !summary.isEmpty {
                                        Text(summary)
                                            .font(.caption)
                                            .foregroundStyle(.secondary)
                                    }
                                    if !incident.riskLabels.isEmpty {
                                        Text(incident.riskLabels.joined(separator: ", "))
                                            .font(.caption2)
                                            .foregroundStyle(.secondary)
                                    }
                                }
                                Divider()
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }


                GroupBox("Android-PC 연결") {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("PC process ID와 Android package name을 매칭합니다. 모바일 세션은 수동 시작/종료와 Android UsageStats sync 흐름에 사용됩니다.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        HStack {
                            TextField("PC process ID", text: $viewModel.gameLinkProcessID)
                                .textFieldStyle(.roundedBorder)
                            TextField("Android package", text: $viewModel.gameLinkAndroidPackage)
                                .textFieldStyle(.roundedBorder)
                            Button("연결 저장") {
                                Task { await viewModel.createGameLink() }
                            }
                            .disabled(viewModel.gameLinkProcessID.isEmpty || viewModel.gameLinkAndroidPackage.isEmpty)
                        }
                        if viewModel.gameLinks.isEmpty {
                            Text("등록된 Android-PC 연결이 없습니다.")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        List(viewModel.gameLinks) { link in
                            HStack {
                                VStack(alignment: .leading, spacing: 4) {
                                    Text(link.pcDisplayName ?? link.pcProcessID)
                                        .font(.headline)
                                    Text(link.androidPackageName)
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                    Text("sync: \(link.syncStrategy)")
                                        .font(.caption2)
                                        .foregroundStyle(.secondary)
                                }
                                Spacer()
                                if let session = viewModel.activeMobileSession(for: link) {
                                    Button("모바일 종료") {
                                        Task { await viewModel.endMobileSession(session) }
                                    }
                                } else {
                                    Button("모바일 시작") {
                                        Task { await viewModel.startMobileSession(link) }
                                    }
                                }
                            }
                        }
                        .frame(minHeight: 140)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
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
                    .frame(minHeight: 180)
                }
            }
            .padding()
        }
        .task { await viewModel.bootstrap() }
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
