import SwiftUI
import AppKit

extension Notification.Name {
    static let homeworkHelperRemoteMainWindowWillShow = Notification.Name("HomeworkHelperRemoteMainWindowWillShow")
}

@MainActor
enum RemoteSharedModel {
    static let viewModel = RemoteDashboardViewModel()
}

@MainActor
final class RemoteAppDelegate: NSObject, NSApplicationDelegate, NSPopoverDelegate {
    private var statusItem: NSStatusItem?
    private let popover = NSPopover()

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(shouldHideMainWindowForLoginLaunch ? .accessory : .regular)
        configureStatusItem()
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(menuBarIconDidChange(_:)),
            name: Notification.Name("HomeworkHelperRemoteMenuBarIconDidChange"),
            object: nil
        )
        Task {
            await RemoteSharedModel.viewModel.bootstrap()
        }
        if shouldHideMainWindowForLoginLaunch {
            DispatchQueue.main.async {
                Self.mainWindows().forEach { $0.orderOut(nil) }
            }
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        false
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        popover.performClose(nil)
        Self.showMainWindow()
        return true
    }

    private var shouldHideMainWindowForLoginLaunch: Bool {
        RemoteLoginItemManager.isEnabled
        && !RemoteSharedModel.viewModel.loginLaunchShowsWindow
        && (ProcessInfo.processInfo.environment["LaunchServicesLaunchReason"] == "LoginItems"
            || ProcessInfo.processInfo.arguments.contains("--launched-at-login"))
    }

    private func configureStatusItem() {
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        item.button?.image = NSImage(systemSymbolName: RemoteSharedModel.viewModel.menuBarIconSymbol, accessibilityDescription: "HomeworkHelper Remote")
        item.button?.target = self
        item.button?.action = #selector(statusItemClicked(_:))
        statusItem = item

        popover.behavior = .transient
        popover.delegate = self
        popover.contentViewController = NSHostingController(rootView: MenuBarPopoverView(viewModel: RemoteSharedModel.viewModel))
    }

    @objc private func statusItemClicked(_ sender: NSStatusBarButton) {
        if popover.isShown {
            popover.performClose(sender)
        } else {
            popover.show(relativeTo: sender.bounds, of: sender, preferredEdge: .minY)
        }
    }

    @objc private func menuBarIconDidChange(_ notification: Notification) {
        let symbol = notification.object as? String ?? RemoteMenuBarIconChoice.defaultSymbol
        statusItem?.button?.image = NSImage(systemSymbolName: symbol, accessibilityDescription: "HomeworkHelper Remote")
    }

    static func showMainWindow() {
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
        NotificationCenter.default.post(name: .homeworkHelperRemoteMainWindowWillShow, object: nil)
        if mainWindows().isEmpty {
            NSApp.sendAction(Selector(("showMainWindow:")), to: nil, from: nil)
        }
        for window in mainWindows() {
            window.makeKeyAndOrderFront(nil)
            window.orderFrontRegardless()
        }
    }

    private static func mainWindows() -> [NSWindow] {
        NSApp.windows.filter { window in
            (window.identifier?.rawValue == "HomeworkHelperRemoteMainWindow"
            || window.title == "HomeworkHelper Remote")
            && String(describing: type(of: window)).contains("Popover") == false
            && window.isReleasedWhenClosed == false
        }
    }
}

@main
struct HomeworkHelperRemoteApp: App {
    @NSApplicationDelegateAdaptor(RemoteAppDelegate.self) private var appDelegate
    @StateObject private var viewModel = RemoteSharedModel.viewModel

    var body: some Scene {
        WindowGroup {
            RemoteDashboardView(viewModel: viewModel)
        }
        .windowResizability(.contentSize)

        Settings {
            RemoteSettingsView(viewModel: viewModel)
                .frame(minWidth: 620, minHeight: 720)
        }
    }
}

struct RemoteDashboardView: View {
    @ObservedObject var viewModel: RemoteDashboardViewModel
    @State private var sidebarVisible = false

    private var targetSize: CGSize {
        let hasVisibleSummary = viewModel.showPlaySummary && viewModel.dashboardSummary != nil
        return RemoteWindowLayout.contentSize(
            cardCount: viewModel.processes.count,
            sidebarVisible: sidebarVisible,
            hasSummary: hasVisibleSummary,
            hasIncidents: !viewModel.beholderIncidents.isEmpty
        )
    }

    var body: some View {
        HStack(spacing: 0) {
            if sidebarVisible {
                RemoteSidebarView(viewModel: viewModel)
                    .frame(width: RemoteWindowLayout.sidebarWidth)
                Divider()
                    .frame(width: RemoteWindowLayout.dividerWidth)
            }

            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    HeaderStatusView(viewModel: viewModel, sidebarVisible: $sidebarVisible)

                    GameSectionView(viewModel: viewModel)

                    if viewModel.showPlaySummary, let summary = viewModel.dashboardSummary {
                        PlaySummaryView(summary: summary)
                    }

                    if !viewModel.beholderIncidents.isEmpty {
                        BeholderIncidentSummaryView(incidents: viewModel.beholderIncidents)
                    }
                }
                .padding(16)
                .frame(width: RemoteWindowLayout.mainContentWidth(cardCount: viewModel.processes.count), alignment: .topLeading)
            }
        }
        .frame(width: targetSize.width, height: targetSize.height)
        .background(
            RemoteWindowAccessor(
                cardCount: viewModel.processes.count,
                sidebarVisible: sidebarVisible,
                hasSummary: viewModel.showPlaySummary && viewModel.dashboardSummary != nil,
                hasIncidents: !viewModel.beholderIncidents.isEmpty
            )
        )
        .onAppear { sidebarVisible = false }
        .onReceive(NotificationCenter.default.publisher(for: .homeworkHelperRemoteMainWindowWillShow)) { _ in
            sidebarVisible = false
        }
        .task { await viewModel.bootstrap() }
    }
}

struct GameSectionView: View {
    @ObservedObject var viewModel: RemoteDashboardViewModel

    var body: some View {
        GroupBox {
            DraggableHorizontalScrollView {
                HStack(spacing: RemoteWindowLayout.gameCardSpacing) {
                    ForEach(viewModel.processes) { process in
                        RemoteGameCard(process: process, viewModel: viewModel) {
                            Task { await viewModel.launch(process) }
                        }
                    }
                }
                .frame(width: RemoteWindowLayout.gameContentWidth(cardCount: viewModel.processes.count), alignment: .leading)
                .padding(.vertical, 2)
            }
            .frame(
                width: RemoteWindowLayout.gameViewportWidth(cardCount: viewModel.processes.count),
                height: RemoteWindowLayout.gameCardHeight + 10
            )
            .clipped()
        } label: {
            HStack {
                Text("게임")
                Spacer()
                Button {
                    Task { await viewModel.refresh() }
                } label: {
                    Label("새로고침", systemImage: "arrow.clockwise")
                        .labelStyle(.iconOnly)
                }
                .buttonStyle(.borderless)
                .controlSize(.small)
                .help("새로고침")
                .disabled(viewModel.isLoading)
            }
            .frame(maxWidth: .infinity)
        }
    }
}

final class InvisibleHorizontalNSScrollView: NSScrollView {
    private var lastDragLocation: NSPoint?

    override func mouseDown(with event: NSEvent) {
        lastDragLocation = convert(event.locationInWindow, from: nil)
        super.mouseDown(with: event)
    }

    override func mouseDragged(with event: NSEvent) {
        guard let lastDragLocation else {
            super.mouseDragged(with: event)
            return
        }
        let current = convert(event.locationInWindow, from: nil)
        let dx = lastDragLocation.x - current.x
        var origin = contentView.bounds.origin
        let documentWidth = documentView?.bounds.width ?? 0
        origin.x = max(0, min(origin.x + dx, max(0, documentWidth - contentView.bounds.width)))
        contentView.scroll(to: origin)
        reflectScrolledClipView(contentView)
        self.lastDragLocation = current
    }
}

struct DraggableHorizontalScrollView<Content: View>: NSViewRepresentable {
    let content: Content

    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    func makeNSView(context: Context) -> InvisibleHorizontalNSScrollView {
        let scrollView = InvisibleHorizontalNSScrollView()
        scrollView.hasHorizontalScroller = false
        scrollView.hasVerticalScroller = false
        scrollView.autohidesScrollers = true
        scrollView.drawsBackground = false
        scrollView.borderType = .noBorder
        scrollView.documentView = NSHostingView(rootView: content)
        return scrollView
    }

    func updateNSView(_ scrollView: InvisibleHorizontalNSScrollView, context: Context) {
        if let hosting = scrollView.documentView as? NSHostingView<Content> {
            hosting.rootView = content
            hosting.frame = NSRect(origin: .zero, size: hosting.fittingSize)
        } else {
            scrollView.documentView = NSHostingView(rootView: content)
        }
    }
}

struct RemoteSidebarView: View {
    @ObservedObject var viewModel: RemoteDashboardViewModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 10) {
                GroupBox("연결") {
                    VStack(alignment: .leading, spacing: 8) {
                        if viewModel.isPaired {
                            SidebarInfoRow(label: "서버", value: viewModel.baseURLText)
                            SidebarInfoRow(label: "디바이스", value: viewModel.deviceName)
                            Text(viewModel.message)
                                .font(.caption2)
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
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                        }

                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }

                GroupBox("PC 전원") {
                    VStack(alignment: .leading, spacing: 8) {
                        if viewModel.status?.power?.configured != true {
                            Text("전원 제어 설정 전입니다. 고급 설정에서 최초 1회만 설정하세요.")
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                        }
                        HStack(spacing: 6) {
                            PowerSquareButton(action: "wake", label: "켜기", systemImage: "power", viewModel: viewModel)
                            PowerSquareButton(action: "sleep", label: "절전", systemImage: "moon.fill", viewModel: viewModel)
                            PowerSquareButton(action: "restart", label: "재시작", systemImage: "arrow.clockwise", viewModel: viewModel)
                            PowerSquareButton(action: "shutdown", label: "끄기", systemImage: "power.circle", viewModel: viewModel)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }

                GroupBox("앱") {
                    HStack {
                        SettingsOpenButton()
                        Spacer(minLength: 0)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            .padding(.vertical, 12)
            .padding(.horizontal, 18)
            .frame(maxWidth: .infinity, alignment: .topLeading)
        }
    }
}

struct SettingsOpenButton: View {
    var body: some View {
        Group {
            if #available(macOS 14.0, *) {
                SettingsLink {
                    Label("설정 열기", systemImage: "gearshape")
                }
            } else {
                Button(action: openSettingsWindowFallback) {
                    Label("설정 열기", systemImage: "gearshape")
                }
            }
        }
        .buttonStyle(.bordered)
    }

    private func openSettingsWindowFallback() {
        NSApp.activate(ignoringOtherApps: true)
        if NSApp.sendAction(Selector(("showSettingsWindow:")), to: nil, from: nil) {
            return
        }
        NSApp.sendAction(Selector(("showPreferencesWindow:")), to: nil, from: nil)
    }
}

struct HeaderStatusView: View {
    @ObservedObject var viewModel: RemoteDashboardViewModel
    @Binding var sidebarVisible: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .center) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("HomeworkHelper Remote")
                        .font(.title.bold())
                    Text("게임 실행, 진행률, 전원 제어를 빠르게 확인합니다.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button {
                    sidebarVisible.toggle()
                } label: {
                    Label(sidebarVisible ? "패널 숨기기" : "패널 보기", systemImage: sidebarVisible ? "sidebar.left" : "sidebar.leading")
                }
                .controlSize(.small)
            }
            if let readiness = viewModel.readiness {
                HStack(spacing: 6) {
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

struct RemoteGameCard: View {
    let process: RemoteProcess
    @ObservedObject var viewModel: RemoteDashboardViewModel
    let launch: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack(spacing: 8) {
                GameIconView(process: process, viewModel: viewModel)
                    .frame(width: 34, height: 34)
                VStack(alignment: .leading, spacing: 1) {
                    Text(process.name)
                        .font(.headline)
                        .lineLimit(1)
                        .minimumScaleFactor(0.68)
                        .allowsTightening(true)
                    Text(process.statusText ?? (process.isRunning ? "실행 중" : "대기"))
                        .font(.caption2)
                        .foregroundStyle(process.isRunning ? .green : .secondary)
                        .lineLimit(1)
                }
                Spacer(minLength: 0)
                Circle()
                    .fill(process.playedToday ? Color.green : Color.secondary.opacity(0.28))
                    .frame(width: 8, height: 8)
                    .help(process.playedToday ? "오늘 실행됨" : "오늘 미실행")
            }

            if let progress = process.progress {
                HStack(spacing: 5) {
                    ResourceIconView(process: process, viewModel: viewModel)
                        .frame(width: 14, height: 14)
                    GameProgressView(progress: progress)
                }
            } else {
                Text("진행률 없음")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }

            Button(action: launch) {
                Label("실행", systemImage: "play.fill")
                    .frame(maxWidth: .infinity)
            }
            .controlSize(.small)
        }
        .padding(10)
        .frame(width: RemoteWindowLayout.gameCardWidth, height: RemoteWindowLayout.gameCardHeight, alignment: .topLeading)
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 14))
        .overlay(
            RoundedRectangle(cornerRadius: 14)
                .stroke(process.isRunning ? Color.green.opacity(0.55) : Color.secondary.opacity(0.16), lineWidth: 1)
        )
    }
}

struct GameIconView: View {
    let process: RemoteProcess
    @ObservedObject var viewModel: RemoteDashboardViewModel
    var preferredSize: Int = 256

    var body: some View {
        Group {
            if let cached = viewModel.cachedIconURL(for: process, preferredSize: preferredSize), let image = NSImage(contentsOf: cached) {
                Image(nsImage: image)
                    .resizable()
                    .interpolation(.high)
                    .antialiased(true)
                    .scaledToFit()
            } else if let remote = viewModel.remoteIconURL(for: process, preferredSize: preferredSize) {
                AsyncImage(url: remote) { phase in
                    switch phase {
                    case .success(let image):
                        image
                            .resizable()
                            .interpolation(.high)
                            .antialiased(true)
                            .scaledToFit()
                    default:
                        fallback
                    }
                }
            } else {
                fallback
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private var fallback: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 8)
                .fill(Color.accentColor.opacity(0.18))
            Text(String(process.name.prefix(1)))
                .font(.headline.bold())
        }
    }
}

struct ResourceIconView: View {
    let process: RemoteProcess
    @ObservedObject var viewModel: RemoteDashboardViewModel
    var preferredSize: Int = 64

    var body: some View {
        Group {
            if let cached = viewModel.cachedResourceIconURL(for: process, preferredSize: preferredSize), let image = NSImage(contentsOf: cached) {
                Image(nsImage: image)
                    .resizable()
                    .interpolation(.high)
                    .antialiased(true)
                    .scaledToFit()
            } else if let remote = viewModel.remoteResourceIconURL(for: process, preferredSize: preferredSize) {
                AsyncImage(url: remote) { phase in
                    switch phase {
                    case .success(let image):
                        image
                            .resizable()
                            .interpolation(.high)
                            .antialiased(true)
                            .scaledToFit()
                    default: fallback
                    }
                }
            } else {
                fallback
            }
        }
    }

    private var fallback: some View {
        Image(systemName: process.progress?.kind == "stamina" ? "bolt.fill" : "clock")
            .font(.caption2)
            .foregroundStyle(process.progress?.kind == "stamina" ? .yellow : .secondary)
    }
}

struct GameProgressView: View {
    let progress: RemoteProcess.Progress

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            ProgressView(value: min(max(progress.percentage, 0), 100), total: 100)
                .controlSize(.small)
            Text(progress.displayText)
                .font(.caption2)
                .foregroundStyle(.secondary)
                .lineLimit(1)
        }
    }
}

struct MenuBarGameRow: View {
    let process: RemoteProcess
    @ObservedObject var viewModel: RemoteDashboardViewModel

    var body: some View {
        HStack(alignment: .center, spacing: 8) {
            GameIconView(process: process, viewModel: viewModel, preferredSize: 256)
                .frame(width: 24, height: 24)
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 5) {
                    Text(process.name)
                        .font(.caption.bold())
                        .lineLimit(1)
                        .minimumScaleFactor(0.72)
                        .allowsTightening(true)
                    Spacer(minLength: 4)
                    HStack(spacing: 3) {
                        Circle()
                            .fill(process.isRunning ? Color.green : Color.secondary.opacity(0.35))
                            .frame(width: 6, height: 6)
                        Circle()
                            .fill(process.playedToday ? Color.blue : Color.secondary.opacity(0.25))
                            .frame(width: 6, height: 6)
                    }
                    .help("\(process.isRunning ? "실행 중" : "대기") · \(process.playedToday ? "오늘 실행" : "오늘 미실행")")
                }
                if let progress = process.progress {
                    HStack(spacing: 5) {
                        ResourceIconView(process: process, viewModel: viewModel, preferredSize: 128)
                            .frame(width: 12, height: 12)
                        ProgressView(value: min(max(progress.percentage, 0), 100), total: 100)
                            .controlSize(.mini)
                        Text(progress.displayText)
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                } else {
                    Text(process.statusText ?? "대기")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct HostStatusPill: View {
    @ObservedObject var viewModel: RemoteDashboardViewModel

    var body: some View {
        Text(viewModel.hostStatusLabel)
            .font(.caption2.bold())
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .foregroundStyle(viewModel.hostStatusColor)
            .background(viewModel.hostStatusColor.opacity(0.14), in: Capsule())
    }
}

struct MenuBarPopoverView: View {
    @ObservedObject var viewModel: RemoteDashboardViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("HomeworkHelper")
                    .font(.headline)
                Spacer()
                HostStatusPill(viewModel: viewModel)
            }
            VStack(alignment: .leading, spacing: 6) {
                ForEach(viewModel.processes.prefix(5)) { process in
                    MenuBarGameRow(process: process, viewModel: viewModel)
                }
                if viewModel.processes.count > 5 {
                    Text("외 \(viewModel.processes.count - 5)개")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
                if viewModel.processes.isEmpty {
                    Text("캐시된 게임 상태가 없습니다.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            HStack(spacing: 8) {
                PowerSquareButton(action: "wake", label: "켜기", systemImage: "power", viewModel: viewModel)
                PowerSquareButton(action: "sleep", label: "절전", systemImage: "moon.fill", viewModel: viewModel)
                PowerSquareButton(action: "restart", label: "재시동", systemImage: "arrow.clockwise", viewModel: viewModel)
                PowerSquareButton(action: "shutdown", label: "끄기", systemImage: "power.circle", viewModel: viewModel)
            }
            Divider()
            HStack(spacing: 8) {
                Button { RemoteAppDelegate.showMainWindow() } label: {
                    Label("창 열기", systemImage: "macwindow")
                        .frame(maxWidth: .infinity)
                }
                Button { Task { await viewModel.refresh() } } label: {
                    Label("새로고침", systemImage: "arrow.clockwise")
                        .frame(maxWidth: .infinity)
                }
                Button { NSApp.terminate(nil) } label: {
                    Label("앱 종료", systemImage: "power")
                        .frame(maxWidth: .infinity)
                }
            }
        }
        .padding(14)
        .frame(width: 360)
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

struct RemoteSettingsView: View {
    @ObservedObject var viewModel: RemoteDashboardViewModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                GroupBox("연결/페어링") {
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
                        Button("Tailscale 서버/호스트 탐색") { Task { await viewModel.discoverTailscale() } }
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

                GroupBox("전원/SSH/SmartThings") {
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

                GroupBox("앱 동작") {
                    VStack(alignment: .leading, spacing: 10) {
                        Toggle("로그인 시 실행", isOn: Binding(
                            get: { viewModel.launchAtLoginEnabled },
                            set: { enabled in viewModel.setLaunchAtLogin(enabled) }
                        ))
                        Toggle("로그인 자동 실행 시 창 표시", isOn: $viewModel.loginLaunchShowsWindow)
                        Toggle("플레이 요약 표시", isOn: $viewModel.showPlaySummary)
                        Picker("메뉴바 아이콘", selection: $viewModel.menuBarIconSymbol) {
                            ForEach(RemoteMenuBarIconChoice.symbols, id: \.self) { symbol in
                                Label(symbol, systemImage: symbol).tag(symbol)
                            }
                        }
                        .pickerStyle(.menu)
                        Text("내장 SF Symbols 중 하나를 메뉴바 아이콘으로 사용합니다.")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            .padding()
        }
    }
}

typealias AdvancedRemoteSettingsView = RemoteSettingsView

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

struct PowerSquareButton: View {
    let action: String
    let label: String
    let systemImage: String
    @ObservedObject var viewModel: RemoteDashboardViewModel

    var body: some View {
        Button {
            Task { await viewModel.power(action) }
        } label: {
            VStack(spacing: 4) {
                Image(systemName: systemImage)
                    .font(.system(size: 16, weight: .semibold))
                Text(label)
                    .font(.caption2)
                    .lineLimit(1)
            }
            .frame(width: 52, height: 52)
            .contentShape(Rectangle())
        }
        .buttonStyle(.bordered)
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
