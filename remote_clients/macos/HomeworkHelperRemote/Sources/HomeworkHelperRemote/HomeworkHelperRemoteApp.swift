import SwiftUI

@main
struct HomeworkHelperRemoteApp: App {
    var body: some Scene {
        WindowGroup {
            RemoteDashboardView()
                .frame(minWidth: 720, minHeight: 520)
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

@MainActor
final class RemoteDashboardViewModel: ObservableObject {
    @Published var baseURLText = "http://127.0.0.1:8000"
    @Published var tokenText = "" {
        didSet { tokenStore.save(tokenText) }
    }
    @Published var pairingCode = ""
    @Published var deviceName = Host.current().localizedName ?? "Mac"
    @Published var gameLinkProcessID = ""
    @Published var gameLinkAndroidPackage = ""
    @Published var powerConfig = RemotePowerConfigPayload()
    @Published var powerConfigResponse: RemotePowerConfigResponse?
    @Published var status: RemoteStatus?
    @Published var dashboardSummary: RemoteDashboardSummary?
    @Published var beholderIncidents: [RemoteBeholderIncident] = []
    @Published var gameLinks: [RemoteGameLink] = []
    @Published var mobileSessions: [RemoteMobileSession] = []
    @Published var processes: [RemoteProcess] = []
    @Published var shortcuts: [RemoteShortcut] = []
    @Published var devices: [RemoteDevice] = []
    @Published var isLoading = false
    @Published var message = "Remote Agent에 연결하세요."

    private let tokenStore = KeychainTokenStore()

    init() {
        tokenText = tokenStore.load()
    }

    private var client: RemoteAPIClient? {
        guard let url = URL(string: baseURLText), url.scheme != nil else { return nil }
        return RemoteAPIClient(baseURL: url, bearerToken: tokenText.isEmpty ? nil : tokenText)
    }

    func refresh() async {
        guard let client else {
            message = "Remote Agent URL이 올바르지 않습니다."
            return
        }
        isLoading = true
        defer { isLoading = false }
        do {
            async let fetchedStatus = client.status()
            async let fetchedSummary = client.dashboardSummary()
            async let fetchedIncidents = client.beholderIncidents()
            async let fetchedGameLinks = client.gameLinks()
            async let fetchedMobileSessions = client.activeMobileSessions()
            async let fetchedPowerConfig = client.powerConfig()
            async let fetchedProcesses = client.processes()
            async let fetchedShortcuts = client.shortcuts()
            status = try await fetchedStatus
            dashboardSummary = try await fetchedSummary
            beholderIncidents = try await fetchedIncidents
            gameLinks = try await fetchedGameLinks
            mobileSessions = try await fetchedMobileSessions
            powerConfigResponse = try await fetchedPowerConfig
            powerConfig = powerConfigResponse?.config ?? RemotePowerConfigPayload()
            processes = try await fetchedProcesses
            shortcuts = try await fetchedShortcuts
            if !tokenText.isEmpty {
                devices = try await client.devices()
            }
            message = "동기화 완료: 게임 \(processes.count)개, 연결 \(gameLinks.count)개, 모바일 세션 \(mobileSessions.count)개, 숏컷 \(shortcuts.count)개"
        } catch {
            message = error.localizedDescription
        }
    }

    func activeMobileSession(for link: RemoteGameLink) -> RemoteMobileSession? {
        mobileSessions.first { $0.gameLinkID == link.id && $0.status == "active" }
    }

    func startMobileSession(_ link: RemoteGameLink) async {
        guard let client else { return }
        do {
            let session = try await client.startMobileSession(gameLinkID: link.id)
            mobileSessions = try await client.activeMobileSessions()
            message = "'\(session.pcDisplayName ?? session.pcProcessID)' 모바일 세션을 시작했습니다."
        } catch {
            message = error.localizedDescription
        }
    }

    func endMobileSession(_ session: RemoteMobileSession) async {
        guard let client else { return }
        do {
            let ended = try await client.endMobileSession(sessionID: session.id)
            mobileSessions = try await client.activeMobileSessions()
            message = "'\(ended.pcDisplayName ?? ended.pcProcessID)' 모바일 세션을 종료했습니다."
        } catch {
            message = error.localizedDescription
        }
    }

    func createGameLink() async {
        guard let client else { return }
        let processID = gameLinkProcessID.trimmingCharacters(in: .whitespacesAndNewlines)
        let packageName = gameLinkAndroidPackage.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !processID.isEmpty, !packageName.isEmpty else {
            message = "PC process ID와 Android package name을 입력하세요."
            return
        }
        do {
            let link = try await client.createGameLink(processID: processID, androidPackageName: packageName)
            gameLinks = try await client.gameLinks()
            gameLinkAndroidPackage = ""
            message = "'\(link.pcDisplayName ?? link.pcProcessID)'와 \(link.androidPackageName) 연결을 저장했습니다."
        } catch {
            message = error.localizedDescription
        }
    }

    func launch(_ process: RemoteProcess) async {
        guard let client else { return }
        do {
            let result = try await client.launchProcess(id: process.id)
            message = result.message
        } catch {
            message = error.localizedDescription
        }
    }

    func open(_ shortcut: RemoteShortcut) async {
        guard let client else { return }
        do {
            let result = try await client.openShortcut(id: shortcut.id)
            message = result.message
        } catch {
            message = error.localizedDescription
        }
    }

    func isPowerActionEnabled(_ action: String) -> Bool {
        guard let status else { return false }
        guard status.capabilities.powerControl, status.power?.configured == true else { return false }
        let supported = status.supportedPowerActions
        return supported.isEmpty || supported.contains(action)
    }

    func power(_ action: String) async {
        guard isPowerActionEnabled(action) else {
            message = "전원 제어 adapter가 설정되지 않았거나 지원하지 않는 명령입니다."
            return
        }
        guard let client else { return }
        do {
            let result = try await client.power(action: action)
            message = result.message
            await refresh()
        } catch {
            message = error.localizedDescription
        }
    }

    func savePowerConfig() async {
        guard let client else { return }
        do {
            let response = try await client.savePowerConfig(powerConfig)
            powerConfigResponse = response
            powerConfig = response.config
            status = try await client.status()
            let supportedActions = response.readiness.supportedActions.joined(separator: ", ")
            message = "전원 설정을 저장했습니다. 지원 명령: \(supportedActions)"
        } catch {
            message = error.localizedDescription
        }
    }

    func confirmPairing() async {
        guard let client else {
            message = "Remote Agent URL이 올바르지 않습니다."
            return
        }
        guard !pairingCode.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            message = "페어링 코드를 입력하세요."
            return
        }
        isLoading = true
        defer { isLoading = false }
        do {
            let response = try await client.confirmPairing(code: pairingCode, deviceName: deviceName)
            tokenText = response.token
            pairingCode = ""
            message = "'\(response.name)' 디바이스 페어링 완료. 토큰을 Keychain에 저장했습니다."
            await refresh()
        } catch {
            message = error.localizedDescription
        }
    }

    func refreshToken() async {
        guard let client else { return }
        do {
            let response = try await client.refreshToken()
            tokenText = response.token
            message = "'\(response.name)' 디바이스 토큰을 갱신하고 Keychain에 저장했습니다."
            await refreshDevices()
        } catch {
            message = error.localizedDescription
        }
    }

    func refreshDevices() async {
        guard let client else { return }
        do {
            devices = try await client.devices()
            message = "등록 디바이스 \(devices.count)개를 불러왔습니다."
        } catch {
            message = error.localizedDescription
        }
    }

    func revoke(_ device: RemoteDevice) async {
        guard let client else { return }
        do {
            let result = try await client.revokeDevice(id: device.id)
            message = result.revoked ? "'\(device.name)' 디바이스 토큰을 폐기했습니다." : "디바이스 토큰 폐기에 실패했습니다."
            if tokenText.isEmpty == false {
                await refreshDevices()
            }
        } catch {
            message = error.localizedDescription
        }
    }
}

struct RemoteDashboardView: View {
    @StateObject private var viewModel = RemoteDashboardViewModel()

    var body: some View {
        NavigationSplitView {
            Form {
                Section("Remote Agent") {
                    TextField("Base URL", text: $viewModel.baseURLText)
                        .textFieldStyle(.roundedBorder)
                    SecureField("Bearer token (선택)", text: $viewModel.tokenText)
                        .textFieldStyle(.roundedBorder)
                    TextField("디바이스 이름", text: $viewModel.deviceName)
                        .textFieldStyle(.roundedBorder)
                    HStack {
                        TextField("페어링 코드", text: $viewModel.pairingCode)
                            .textFieldStyle(.roundedBorder)
                        Button("페어링") {
                            Task { await viewModel.confirmPairing() }
                        }
                        .disabled(viewModel.isLoading)
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
