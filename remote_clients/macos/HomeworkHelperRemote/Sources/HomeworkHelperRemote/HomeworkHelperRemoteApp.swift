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
    @Published var status: RemoteStatus?
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
            async let fetchedProcesses = client.processes()
            async let fetchedShortcuts = client.shortcuts()
            status = try await fetchedStatus
            processes = try await fetchedProcesses
            shortcuts = try await fetchedShortcuts
            if !tokenText.isEmpty {
                devices = try await client.devices()
            }
            message = "동기화 완료: 게임 \(processes.count)개, 숏컷 \(shortcuts.count)개"
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

                    Section("등록 디바이스") {
                        Button {
                            Task { await viewModel.refreshDevices() }
                        } label: {
                            Label("디바이스 새로고침", systemImage: "person.2")
                        }
                        .disabled(viewModel.tokenText.isEmpty || viewModel.isLoading)

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
