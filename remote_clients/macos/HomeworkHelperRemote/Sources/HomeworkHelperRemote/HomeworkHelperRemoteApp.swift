import SwiftUI
import AppKit

extension Notification.Name {
    static let homeworkHelperRemoteMainWindowWillShow = Notification.Name("HomeworkHelperRemoteMainWindowWillShow")
    static let homeworkHelperRemoteToggleSidebar = Notification.Name("HomeworkHelperRemoteToggleSidebar")
    static let homeworkHelperRemoteRefreshRequested = Notification.Name("HomeworkHelperRemoteRefreshRequested")
}

@MainActor
enum RemoteSharedModel {
    private static var tokenStore: any RemoteTokenStore {
        RemoteUITestFlags.skipExternalState
            ? InMemoryTokenStore(initialToken: "ui-test-token")
            : KeychainTokenStore()
    }

    static let viewModel = RemoteDashboardViewModel(
        tokenStore: tokenStore,
        bootstrapEnabled: !RemoteUITestFlags.skipExternalState
    )
}

@MainActor
final class RemoteAppDelegate: NSObject, NSApplicationDelegate, NSPopoverDelegate {
    static let mainWindowIdentifier = "HomeworkHelperRemoteMainWindow"
    static let mainWindowTitle = "HomeworkHelper Remote"

    private static var isOpeningMainWindow = false
    private static var uiTestMainWindow: NSWindow?

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
        if RemoteUITestFlags.showWindow {
            DispatchQueue.main.async {
                Self.showUITestMainWindow()
            }
        } else if shouldHideMainWindowForLoginLaunch {
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
        guard !RemoteUITestFlags.skipExternalState else { return false }
        return RemoteLoginItemManager.isEnabled
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
        if let window = deduplicateMainWindows() {
            isOpeningMainWindow = false
            focusMainWindow(window)
            return
        }
        if RemoteUITestFlags.showWindow {
            showUITestMainWindow()
            return
        }
        guard !isOpeningMainWindow else { return }
        isOpeningMainWindow = true
        NSApp.sendAction(Selector(("showMainWindow:")), to: nil, from: nil)
        DispatchQueue.main.async {
            isOpeningMainWindow = false
            if let window = deduplicateMainWindows() {
                focusMainWindow(window)
            }
        }
    }



    static func showUITestMainWindow() {
        if let window = uiTestMainWindow {
            focusMainWindow(window)
            settleUITestWindows(preferred: window)
            return
        }

        let initialSize = RemoteWindowLayout.contentSize(
            cardCount: max(1, RemoteSharedModel.viewModel.processes.count),
            sidebarVisible: true,
            hasSummary: RemoteSharedModel.viewModel.showPlaySummary && RemoteSharedModel.viewModel.dashboardSummary != nil,
            hasIncidents: !RemoteSharedModel.viewModel.beholderIncidents.isEmpty
        )
        let window = RemoteMainWindow(
            contentRect: NSRect(origin: .zero, size: initialSize),
            styleMask: [.borderless],
            backing: .buffered,
            defer: false
        )
        window.isReleasedWhenClosed = false
        window.contentView = NSHostingView(rootView: RemoteDashboardView(viewModel: RemoteSharedModel.viewModel))
        prepareMainWindow(window)
        window.center()
        uiTestMainWindow = window
        focusMainWindow(window)
        settleUITestWindows(preferred: window)
    }

    private static func settleUITestWindows(preferred window: NSWindow) {
        for delay in [0.2, 1.0, 2.0, 3.5] {
            DispatchQueue.main.asyncAfter(deadline: .now() + delay) {
                for candidate in NSApp.windows where candidate !== window {
                    let typeName = String(describing: type(of: candidate))
                    guard typeName.contains("Popover") == false,
                          candidate.frame.width > 100,
                          candidate.frame.height > 100 else {
                        continue
                    }
                    candidate.orderOut(nil)
                }
                _ = deduplicateMainWindows(preferred: window)
                focusMainWindow(window)
            }
        }
    }

    static func deduplicateMainWindows(preferred preferredWindow: NSWindow? = nil) -> NSWindow? {
        let candidates = mainWindows()
        guard !candidates.isEmpty else { return nil }
        let keeper = preferredWindow.flatMap { preferred in
            candidates.first { $0 === preferred }
        } ?? candidates.first(where: { $0.isKeyWindow })
            ?? candidates.first(where: { $0.isVisible })
            ?? candidates[0]
        for window in candidates where window !== keeper {
            window.orderOut(nil)
        }
        return keeper
    }

    static func prepareMainWindow(_ window: NSWindow) {
        window.title = mainWindowTitle
        window.identifier = NSUserInterfaceItemIdentifier(mainWindowIdentifier)
        isOpeningMainWindow = false
        _ = deduplicateMainWindows(preferred: window)
    }

    private static func focusMainWindow(_ window: NSWindow) {
        window.makeKeyAndOrderFront(nil)
        window.orderFrontRegardless()
    }

    static func hideMainWindow() {
        mainWindows().forEach { $0.orderOut(nil) }
        NSApp.setActivationPolicy(.accessory)
    }

    static func openSettingsWindow() {
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
        if NSApp.sendAction(Selector(("showSettingsWindow:")), to: nil, from: nil) {
            return
        }
        NSApp.sendAction(Selector(("showPreferencesWindow:")), to: nil, from: nil)
    }

    private static func mainWindows() -> [NSWindow] {
        NSApp.windows.filter(isMainWindowCandidate)
    }

    private static func isMainWindowCandidate(_ window: NSWindow) -> Bool {
        let typeName = String(describing: type(of: window))
        guard typeName.contains("Popover") == false,
              window.isReleasedWhenClosed == false else {
            return false
        }
        return window.identifier?.rawValue == mainWindowIdentifier
            || window.title == mainWindowTitle
    }
}

@main
struct HomeworkHelperRemoteApp: App {
    @NSApplicationDelegateAdaptor(RemoteAppDelegate.self) private var appDelegate
    @StateObject private var viewModel = RemoteSharedModel.viewModel

    var body: some Scene {
        Window(RemoteAppDelegate.mainWindowTitle, id: RemoteAppDelegate.mainWindowIdentifier) {
            if RemoteUITestFlags.showWindow {
                Color.clear
                    .frame(width: 1, height: 1)
            } else {
                RemoteDashboardView(viewModel: viewModel)
            }
        }
        .windowResizability(.contentSize)
        .commands {
            CommandMenu("원격") {
                Button("새로고침") {
                    Task { await viewModel.refresh() }
                }
                .keyboardShortcut("r", modifiers: .command)

                Button("패널 표시/숨김") {
                    NotificationCenter.default.post(name: .homeworkHelperRemoteToggleSidebar, object: nil)
                }
                .keyboardShortcut("s", modifiers: [.command, .shift])

                Divider()

                Button("창 열기") {
                    RemoteAppDelegate.showMainWindow()
                }

                Button("창 숨기기") {
                    RemoteAppDelegate.hideMainWindow()
                }
                .keyboardShortcut("w", modifiers: .command)

                if #available(macOS 14.0, *) {
                    SettingsLink {
                        Text("설정…")
                    }
                    .keyboardShortcut(",", modifiers: .command)
                } else {
                    Button("설정…") {
                        RemoteAppDelegate.openSettingsWindow()
                    }
                    .keyboardShortcut(",", modifiers: .command)
                }
            }
        }

        Settings {
            RemoteSettingsView(viewModel: viewModel)
                .frame(minWidth: 620, minHeight: 720)
        }
    }
}

struct RemoteDashboardView: View {
    @ObservedObject var viewModel: RemoteDashboardViewModel
    @State private var sidebarVisible = RemoteDashboardView.showsSidebarForUITest

    private static var showsSidebarForUITest: Bool {
        RemoteUITestFlags.showSidebar
    }

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
        GlassEffectContainer(spacing: 10) {
            ZStack {
                RemoteAppKitLiquidGlassBackground()
                    .ignoresSafeArea()
                RemoteWindowHitTestShield()
                    .ignoresSafeArea()
                HStack(spacing: 0) {
                    if sidebarVisible {
                        RemoteSidebarView(viewModel: viewModel)
                            .frame(width: RemoteWindowLayout.sidebarWidth)
                        Divider()
                            .frame(width: RemoteWindowLayout.dividerWidth)
                    }

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
                    .padding(RemoteWindowLayout.mainContentInset)
                    .frame(width: RemoteWindowLayout.mainContentWidth(cardCount: viewModel.processes.count), alignment: .topLeading)
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: RemoteWindowLayout.windowCornerRadius, style: .continuous))
            .contentShape(Rectangle())
            .background(Color.black.opacity(0.001))
        }
        .frame(width: targetSize.width, height: targetSize.height)
        .buttonStyle(.glass)
        .background(
            RemoteWindowAccessor(
                cardCount: viewModel.processes.count,
                sidebarVisible: sidebarVisible,
                hasSummary: viewModel.showPlaySummary && viewModel.dashboardSummary != nil,
                hasIncidents: !viewModel.beholderIncidents.isEmpty
            )
        )
        .onAppear {
            if !Self.showsSidebarForUITest {
                sidebarVisible = false
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: .homeworkHelperRemoteMainWindowWillShow)) { _ in
            if !Self.showsSidebarForUITest {
                sidebarVisible = false
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: .homeworkHelperRemoteToggleSidebar)) { _ in
            sidebarVisible.toggle()
        }
        .onReceive(NotificationCenter.default.publisher(for: .homeworkHelperRemoteRefreshRequested)) { _ in
            Task { await viewModel.refresh() }
        }
        .onExitCommand {
            RemoteAppDelegate.hideMainWindow()
        }
        .task { await viewModel.bootstrap() }
    }
}

struct GameSectionView: View {
    @ObservedObject var viewModel: RemoteDashboardViewModel

    var body: some View {
        RemoteGlassGroupBox {
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
                height: RemoteWindowLayout.gameCardHeight + 6
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
                .buttonStyle(.glass)
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
        VStack(alignment: .leading, spacing: 12) {
            SidebarChromeRow()
            sidebarConnectionSection
            Divider().opacity(0.35)
            sidebarPowerSection
            Divider().opacity(0.35)
            sidebarAppSection
        }
        .padding(.horizontal, RemoteWindowLayout.sidebarInset)
        .padding(.top, 18)
        .padding(.bottom, 18)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }

    private var sidebarConnectionSection: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("연결")
                .font(.headline)
            if viewModel.isPaired {
                SidebarInfoRow(label: "서버", value: viewModel.baseURLText)
                SidebarInfoRow(label: "디바이스", value: viewModel.deviceName)
                Text(viewModel.message)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
            } else {
                TextField("http://windows-tailnet-ip:8000", text: $viewModel.baseURLText)
                    .textFieldStyle(.roundedBorder)
                TextField("MacBook", text: $viewModel.deviceName)
                    .textFieldStyle(.roundedBorder)
                HStack(spacing: 6) {
                    TextField("6자리 코드", text: $viewModel.pairingCode)
                        .textFieldStyle(.roundedBorder)
                    Button("페어링") {
                        Task { await viewModel.confirmPairing() }
                    }
                    .disabled(viewModel.isLoading)
                }
                Text("페어링 후 토큰/기기 관리는 설정에서 관리합니다.")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var sidebarPowerSection: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("PC 전원")
                .font(.headline)
            if viewModel.status?.power?.configured != true {
                Text("전원 제어 설정 전입니다. 최초 1회만 설정하세요.")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
            HStack(spacing: 6) {
                PowerSquareButton(action: "wake", label: "켜기", systemImage: "power", viewModel: viewModel)
                PowerSquareButton(action: "sleep", label: "절전", systemImage: "moon.fill", viewModel: viewModel)
                PowerSquareButton(action: "restart", label: "재시작", systemImage: "arrow.clockwise", viewModel: viewModel)
                PowerSquareButton(action: "shutdown", label: "끄기", systemImage: "power.circle", viewModel: viewModel)
            }
            .fixedSize(horizontal: true, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var sidebarAppSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("앱")
                .font(.headline)
            SettingsOpenButton()
                .controlSize(.small)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct SidebarChromeRow: View {
    var body: some View {
        HStack(alignment: .center) {
            WindowTrafficButtons()
            Spacer()
            Image(systemName: "sidebar.left")
                .font(.title3)
                .foregroundStyle(.secondary)
        }
        .frame(height: RemoteWindowLayout.sidebarChromeHeight, alignment: .top)
    }
}

struct WindowTrafficButtons: View {
    var body: some View {
        HStack(spacing: 12) {
            WindowChromeButton(color: .red, accessibilityLabel: "창 닫기") {
                RemoteAppDelegate.hideMainWindow()
            }
            WindowChromeButton(color: .yellow, accessibilityLabel: "창 최소화") {
                NSApp.keyWindow?.miniaturize(nil)
            }
            WindowChromeButton(color: .green, accessibilityLabel: "창 확대") {
                NSApp.keyWindow?.zoom(nil)
            }
        }
    }
}

struct WindowChromeButton: View {
    let color: Color
    let accessibilityLabel: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Circle()
                .fill(color)
                .frame(width: 14, height: 14)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(accessibilityLabel)
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
        .buttonStyle(.glass)
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
                if !sidebarVisible {
                    WindowTrafficButtons()
                        .padding(.trailing, 8)
                }
                VStack(alignment: .leading, spacing: 4) {
                    Text("HomeworkHelper Remote")
                        .font(.title.bold())
                }
                Spacer()
                Button {
                    sidebarVisible.toggle()
                } label: {
                    Label(sidebarVisible ? "패널 숨기기" : "패널 보기", systemImage: sidebarVisible ? "sidebar.left" : "sidebar.leading")
                }
                .buttonStyle(.glass)
                .controlSize(.small)
            }
            .frame(height: 34, alignment: .center)
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
        .frame(height: RemoteWindowLayout.headerHeight, alignment: .top)
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
                    .frame(width: 30, height: 30)
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
                    GameProgressView(progress: progress, viewModel: viewModel)
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
            .buttonStyle(.glassProminent)
            .controlSize(.small)
        }
        .padding(9)
        .frame(width: RemoteWindowLayout.gameCardWidth, height: RemoteWindowLayout.gameCardHeight, alignment: .topLeading)
        .remoteGlass(.card, interactive: true)
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
    var displaySize: CGFloat = 34

    var body: some View {
        Group {
            if let image = viewModel.displayIconImage(for: process, preferredSize: preferredSize, displayPointSize: displaySize) {
                Image(nsImage: image)
                    .interpolation(.none)
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
    var preferredSize: Int = 128
    var displaySize: CGFloat = 14

    var body: some View {
        Group {
            if let image = viewModel.displayResourceIconImage(for: process, preferredSize: preferredSize, displayPointSize: displaySize) {
                Image(nsImage: image)
                    .interpolation(.none)
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
    @ObservedObject var viewModel: RemoteDashboardViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            ProgressView(value: min(max(progress.percentage, 0), 100), total: 100)
                .controlSize(.small)
            Text(viewModel.progressDisplayText(progress))
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
            GameIconView(process: process, viewModel: viewModel, preferredSize: 256, displaySize: 24)
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
                        ResourceIconView(process: process, viewModel: viewModel, preferredSize: 128, displaySize: 12)
                            .frame(width: 12, height: 12)
                        ProgressView(value: min(max(progress.percentage, 0), 100), total: 100)
                            .controlSize(.mini)
                        Text(viewModel.progressDisplayText(progress))
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
            .remoteGlass(.pill, tint: viewModel.hostStatusColor.opacity(0.20))
    }
}

struct MenuBarPopoverView: View {
    @ObservedObject var viewModel: RemoteDashboardViewModel

    var body: some View {
        GlassEffectContainer(spacing: 8) {
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
            .remoteGlass(.popover)
            .buttonStyle(.glass)
            .frame(width: 360)
        }
    }
}

struct PlaySummaryView: View {
    let summary: RemoteDashboardSummary

    var body: some View {
        RemoteGlassGroupBox("플레이 요약") {
            VStack(alignment: .leading, spacing: 7) {
                HStack(alignment: .firstTextBaseline) {
                    Text("\(summary.range.start) ~ \(summary.range.end)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Spacer(minLength: 8)
                    if let topGame = summary.metrics.topGame {
                        Text("Top: \(topGame.displayName) · \(formatDuration(topGame.totalSeconds)) · \(topGame.sessionCount)회")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                }

                HStack(spacing: 12) {
                    SummaryMetric(label: "총 플레이", value: formatDuration(summary.metrics.totalSeconds))
                    SummaryMetric(label: "일평균", value: formatDuration(summary.metrics.dailyAverageSeconds))
                    SummaryMetric(label: "세션", value: "\(summary.metrics.sessionCount)")
                    SummaryMetric(label: "플레이 일수", value: "\(summary.metrics.playedDays)")
                }

                if let mobile = summary.mobileMetrics {
                    Divider().opacity(0.45)
                    Text("모바일 \(formatDuration(mobile.totalSeconds)) · 세션 \(mobile.sessionCount) · 활성 \(mobile.activeSessionCount)" + mobileTopSuffix(mobile))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func mobileTopSuffix(_ mobile: RemoteDashboardSummary.MobileMetrics) -> String {
        guard let topMobileGame = mobile.topGame else { return "" }
        return " · Top: \(topMobileGame.displayName)"
    }
}

struct BeholderIncidentSummaryView: View {
    let incidents: [RemoteBeholderIncident]

    var body: some View {
        RemoteGlassGroupBox("Beholder 알림") {
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
        GlassEffectContainer(spacing: 12) {
            TabView {
                settingsConnectionTab
                .tabItem { Label("연결", systemImage: "link") }
            settingsPowerTab
                .tabItem { Label("전원", systemImage: "bolt") }
            settingsDevicesTab
                .tabItem { Label("기기", systemImage: "display.2") }
            settingsAndroidTab
                .tabItem { Label("Android", systemImage: "app.connected.to.app.below.fill") }
                settingsAppTab
                    .tabItem { Label("앱", systemImage: "gearshape") }
            }
            .remoteGlass(.settings)
        }
        .padding()
        .buttonStyle(.glass)
    }

    private var settingsConnectionTab: some View {
        SettingsTabScrollView {
            RemoteGlassGroupBox("연결/페어링") {
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

            RemoteGlassGroupBox("Tailscale") {
                VStack(alignment: .leading, spacing: 8) {
                    Button("Tailscale 서버/호스트 탐색") { Task { await viewModel.discoverTailscale() } }
                    if let local = viewModel.localTailscale {
                        SidebarInfoRow(label: "로컬 상태", value: local.message)
                        if !local.selfIPs.isEmpty {
                            SidebarInfoRow(label: "이 Mac", value: local.selfIPs.joined(separator: ", "))
                        }
                        ForEach(local.suggestedBaseURLs, id: \.self) { url in
                            Button(url) { viewModel.applySuggestedBaseURL(url) }
                                .buttonStyle(.glass)
                        }
                    }
                    if let serverTailscale = viewModel.serverTailscaleEnsure {
                        SidebarInfoRow(label: "서버 Tailscale", value: serverTailscale.message)
                        SidebarInfoRow(label: "서버 IP", value: serverTailscale.after.selfIPs.isEmpty ? "없음" : serverTailscale.after.selfIPs.joined(separator: ", "))
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }

    private var settingsPowerTab: some View {
        SettingsTabScrollView {
            RemoteGlassGroupBox("전원/SSH/SmartThings") {
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
                            .buttonStyle(.glass)
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }

    private var settingsDevicesTab: some View {
        SettingsTabScrollView {
            RemoteGlassGroupBox("기기 관리") {
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
                                    .buttonStyle(.glass)
                            } else {
                                Text("폐기됨").font(.caption).foregroundStyle(.secondary)
                            }
                        }
                        Divider()
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }

    private var settingsAndroidTab: some View {
        SettingsTabScrollView {
            RemoteGlassGroupBox("Android-PC 연결") {
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
    }

    private var settingsAppTab: some View {
        SettingsTabScrollView {
            RemoteGlassGroupBox("앱 동작") {
                VStack(alignment: .leading, spacing: 10) {
                    Toggle("로그인 시 실행", isOn: Binding(
                        get: { viewModel.launchAtLoginEnabled },
                        set: { enabled in viewModel.setLaunchAtLogin(enabled) }
                    ))
                    Toggle("로그인 자동 실행 시 창 표시", isOn: $viewModel.loginLaunchShowsWindow)
                    Toggle("플레이 요약 표시", isOn: $viewModel.showPlaySummary)
                    Picker("비 HoYoLab 진행률 표시", selection: $viewModel.cycleProgressDisplayMode) {
                        ForEach(CycleProgressDisplayMode.allCases) { mode in
                            Text(mode.label).tag(mode)
                        }
                    }
                    .pickerStyle(.segmented)
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
    }
}

struct SettingsTabScrollView<Content: View>: View {
    @ViewBuilder let content: Content

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                content
            }
            .padding(.vertical, 8)
            .frame(maxWidth: .infinity, alignment: .topLeading)
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


struct SidebarPowerButton: View {
    let action: String
    let label: String
    let systemImage: String
    @ObservedObject var viewModel: RemoteDashboardViewModel

    var body: some View {
        Button {
            Task { await viewModel.power(action) }
        } label: {
            Label(label, systemImage: systemImage)
                .font(.caption)
                .frame(maxWidth: .infinity)
        }
        .buttonStyle(.bordered)
        .controlSize(.small)
        .disabled(viewModel.isLoading || !viewModel.isPowerActionEnabled(action))
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
            .frame(width: 48, height: 48)
            .contentShape(Rectangle())
        }
        .buttonStyle(.glass)
        .disabled(viewModel.isLoading || !viewModel.isPowerActionEnabled(action))
        .frame(width: 48, height: 48)
        .fixedSize()
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
        .remoteGlass(.section)
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
        .remoteGlass(.pill)
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
