import SwiftUI

@main
struct HomeworkHelperRemoteApp: App {
    var body: some Scene {
        WindowGroup {
            RemoteDashboardView()
                .frame(minWidth: 1100, minHeight: 680)
        }
        MenuBarExtra("HomeworkHelper", systemImage: "gamecontroller") {
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
            Form {
                Section("Remote Agent") {
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
                    Button {
                        Task { await viewModel.refresh() }
                    } label: {
                        Label(viewModel.isLoading ? "연결 중..." : "새로고침", systemImage: "arrow.clockwise")
                    }
                    .disabled(viewModel.isLoading)
                    Text(viewModel.message)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                if let status = viewModel.status {
                    Section("상태") {
                        LabeledContent("API", value: status.remoteAPIVersion)
                        LabeledContent("게임", value: "\(status.counts.processes)")
                        LabeledContent("숏컷", value: "\(status.counts.shortcuts)")
                        LabeledContent("대시보드 요약", value: status.capabilities.dashboardSummary ? "사용 가능" : "미지원")
                        LabeledContent("Beholder", value: status.capabilities.beholderIncidents ? "\(viewModel.beholderIncidents.count)건" : "미지원")
                        LabeledContent("Android-PC 연결", value: status.capabilities.gameLinks ? "\(viewModel.gameLinks.count)개" : "미지원")
                        LabeledContent("모바일 세션", value: status.capabilities.mobileSessions ? "\(viewModel.mobileSessions.count)개" : "미지원")
                        LabeledContent("전원 제어", value: status.capabilities.powerControl ? "설정됨" : "미설정")
                        if let power = status.power {
                            LabeledContent("전원 상태", value: power.status ?? "unknown")
                            LabeledContent("지원 명령", value: power.supportedActions.isEmpty ? "없음" : power.supportedActions.joined(separator: ", "))
                            if let targetHost = power.targetHost, !targetHost.isEmpty {
                                LabeledContent("대상", value: targetHost)
                            }
                        }
                    }

                    Section("PC 전원") {
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

                    Section("전원 설정") {
                        if let response = viewModel.powerConfigResponse {
                            LabeledContent("설정 파일", value: response.configPath)
                            LabeledContent("저장 상태", value: response.configExists ? "있음" : "없음")
                            LabeledContent("지원 명령", value: response.readiness.supportedActions.isEmpty ? "없음" : response.readiness.supportedActions.joined(separator: ", "))
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
                        Button("전원 설정 저장") {
                            Task { await viewModel.savePowerConfig() }
                        }
                        Text("저장은 고정된 remote_power_config.json만 갱신하며 전원 명령은 실행하지 않습니다.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }

                    Section("등록 디바이스") {
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
                        }
                    }
                }
            }
            .navigationTitle("HomeworkHelper")
            .navigationSplitViewColumnWidth(min: 340, ideal: 390, max: 480)
        } detail: {
            VStack(alignment: .leading, spacing: 16) {
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
        .task { await viewModel.refresh() }
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
