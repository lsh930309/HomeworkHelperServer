import SwiftUI
import AppKit

extension Notification.Name {
    static let homeworkHelperRemoteMainWindowWillShow = Notification.Name("HomeworkHelperRemoteMainWindowWillShow")
    static let homeworkHelperRemoteToggleSidebar = Notification.Name("HomeworkHelperRemoteToggleSidebar")
    static let homeworkHelperRemoteRefreshRequested = Notification.Name("HomeworkHelperRemoteRefreshRequested")
    static let homeworkHelperRemoteOpenSettings = Notification.Name("HomeworkHelperRemoteOpenSettings")
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
    static let placeholderWindowIdentifier = "HomeworkHelperRemotePlaceholderWindow"
    static let placeholderWindowTitle = "HomeworkHelper Remote Hidden"

    private static weak var shared: RemoteAppDelegate?
    private static var isOpeningMainWindow = false
    private static var uiTestMainWindow: NSWindow?
    private static var uiTestPopoverWindow: NSWindow?

    private var statusItem: NSStatusItem?
    private var statusItemClickMonitor: Any?
    private let popover = NSPopover()

    func applicationDidFinishLaunching(_ notification: Notification) {
        Self.shared = self
        NSApp.setActivationPolicy(.accessory)
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
        DispatchQueue.main.async {
            Self.schedulePlaceholderHide()
        }
        if RemoteUITestFlags.openSettings {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                Self.openSettingsWindow()
            }
        } else if RemoteUITestFlags.clickStatusItem {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                Self.shared?.clickStatusItemForUITest()
            }
        } else if RemoteUITestFlags.showPopover || RemoteUITestFlags.showWindow {
            DispatchQueue.main.async {
                Self.showUITestPopoverWindow()
            }
        } else if shouldHideMainWindowForLoginLaunch {
            DispatchQueue.main.async { Self.schedulePlaceholderHide() }
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        false
    }

    func applicationWillTerminate(_ notification: Notification) {
        removeStatusItemClickMonitor()
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showPopoverFromStatusItem()
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
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        configureStatusButton(item.button, symbol: RemoteSharedModel.viewModel.menuBarIconSymbol)
        item.button?.target = self
        item.button?.action = #selector(RemoteAppDelegate.statusItemClicked(_:))
        item.button?.sendAction(on: [.leftMouseDown])
        item.button?.toolTip = "HomeworkHelper Remote"
        item.button?.isEnabled = true
        statusItem = item
        installStatusItemClickMonitor()

        popover.behavior = .transient
        popover.delegate = self
        popover.contentViewController = Self.makePopoverController()
        updatePopoverContentSize()
    }

    private func configureStatusButton(_ button: NSStatusBarButton?, symbol: String) {
        guard let button else { return }
        if let image = NSImage(systemSymbolName: symbol, accessibilityDescription: "HomeworkHelper Remote") {
            image.isTemplate = true
            button.image = image
            button.title = ""
        } else {
            button.image = nil
            button.title = "HH"
        }
        button.imagePosition = .imageOnly
    }

    @objc func statusItemClicked(_ sender: Any?) {
        guard let button = sender as? NSStatusBarButton ?? statusItem?.button else {
            Self.openSettingsWindow()
            return
        }
        togglePopover(relativeTo: button)
    }

    func clickStatusItemForUITest() {
        guard let button = statusItem?.button else {
            showPopoverFromStatusItem()
            return
        }
        statusItemClicked(button)
    }

    private func installStatusItemClickMonitor() {
        guard statusItemClickMonitor == nil else { return }
        statusItemClickMonitor = NSEvent.addLocalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown]) { [weak self] event in
            guard let self,
                  let button = self.statusItem?.button,
                  event.window === button.window else {
                return event
            }
            self.togglePopover(relativeTo: button)
            return nil
        }
    }

    private func removeStatusItemClickMonitor() {
        if let monitor = statusItemClickMonitor {
            NSEvent.removeMonitor(monitor)
            statusItemClickMonitor = nil
        }
    }

    private static func makePopoverController() -> NSHostingController<MenuBarPopoverView> {
        let controller = NSHostingController(rootView: MenuBarPopoverView(viewModel: RemoteSharedModel.viewModel))
        controller.view.wantsLayer = true
        controller.view.layer?.backgroundColor = NSColor.clear.cgColor
        return controller
    }

    private func currentPopoverContentSize() -> CGSize {
        RemotePopoverLayout.contentSize(
            processes: RemoteSharedModel.viewModel.processes,
            showsPairingCTA: !RemoteSharedModel.viewModel.isPaired,
            showsSummary: RemoteSharedModel.viewModel.showPlaySummary && RemoteSharedModel.viewModel.dashboardSummary != nil,
            incidentCount: RemoteSharedModel.viewModel.beholderIncidents.count
        )
    }

    private func updatePopoverContentSize() {
        popover.contentSize = currentPopoverContentSize()
    }

    private func showPopoverFromStatusItem() {
        guard let button = statusItem?.button else {
            Self.openSettingsWindow()
            return
        }
        showPopover(relativeTo: button)
    }

    private func togglePopover(relativeTo button: NSStatusBarButton) {
        if popover.isShown {
            popover.performClose(button)
            return
        }
        showPopover(relativeTo: button)
    }

    private func showPopover(relativeTo button: NSStatusBarButton) {
        updatePopoverContentSize()
        NSApp.setActivationPolicy(.accessory)
        NSApp.activate(ignoringOtherApps: true)
        popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
    }

    @objc private func menuBarIconDidChange(_ notification: Notification) {
        let symbol = notification.object as? String ?? RemoteMenuBarIconChoice.defaultSymbol
        configureStatusButton(statusItem?.button, symbol: symbol)
    }

    static func showPrimaryInterface() {
        if let shared {
            shared.showPopoverFromStatusItem()
        } else {
            openSettingsWindow()
        }
    }



    static func showUITestMainWindow() {
        showUITestPopoverWindow()
    }

    static func showUITestPopoverWindow() {
        if let window = uiTestPopoverWindow {
            focusMainWindow(window)
            settleUITestPopoverWindow(preferred: window)
            return
        }
        let window = NSWindow(
            contentRect: NSRect(origin: .zero, size: CGSize(width: 392, height: 500)),
            styleMask: [.borderless],
            backing: .buffered,
            defer: false
        )
        window.isReleasedWhenClosed = false
        window.isOpaque = false
        window.backgroundColor = .clear
        window.hasShadow = true
        window.contentView = NSHostingView(rootView: MenuBarPopoverView(viewModel: RemoteSharedModel.viewModel))
        window.setContentSize(RemotePopoverLayout.contentSize(
            processes: RemoteSharedModel.viewModel.processes,
            showsPairingCTA: !RemoteSharedModel.viewModel.isPaired,
            showsSummary: RemoteSharedModel.viewModel.showPlaySummary && RemoteSharedModel.viewModel.dashboardSummary != nil,
            incidentCount: RemoteSharedModel.viewModel.beholderIncidents.count
        ))
        window.center()
        uiTestPopoverWindow = window
        focusMainWindow(window)
        settleUITestPopoverWindow(preferred: window)
    }

    private static func settleUITestPopoverWindow(preferred window: NSWindow) {
        for delay in [0.0, 0.2, 0.8, 1.6, 3.0] {
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
                focusMainWindow(window)
            }
        }
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
        window.title = ""
        window.identifier = NSUserInterfaceItemIdentifier(mainWindowIdentifier)
        isOpeningMainWindow = false
        _ = deduplicateMainWindows(preferred: window)
    }

    private static func focusMainWindow(_ window: NSWindow) {
        window.makeKeyAndOrderFront(nil)
        window.orderFrontRegardless()
    }

    static func hideMainWindow() {
        hidePlaceholderWindows()
        NSApp.setActivationPolicy(.accessory)
    }

    static func hidePlaceholderWindows() {
        NSApp.windows
            .filter { $0.identifier?.rawValue == placeholderWindowIdentifier || $0.title == placeholderWindowTitle }
            .forEach { $0.orderOut(nil) }
    }

    static func schedulePlaceholderHide() {
        for delay in [0.0, 0.1, 0.5, 1.5] {
            DispatchQueue.main.asyncAfter(deadline: .now() + delay) {
                hidePlaceholderWindows()
            }
        }
    }

    static func openSettingsWindow() {
        shared?.popover.performClose(nil)
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
        NotificationCenter.default.post(name: .homeworkHelperRemoteOpenSettings, object: nil)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) {
            guard NSApp.windows.contains(where: { $0.isVisible && $0.identifier?.rawValue != placeholderWindowIdentifier }) == false else {
                return
            }
            if NSApp.sendAction(Selector(("showSettingsWindow:")), to: nil, from: nil) {
                return
            }
            NSApp.sendAction(Selector(("showPreferencesWindow:")), to: nil, from: nil)
        }
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
        Window(RemoteAppDelegate.placeholderWindowTitle, id: RemoteAppDelegate.placeholderWindowIdentifier) {
            Color.clear
                .frame(width: 160, height: 96)
                .background(RemotePlaceholderWindowAccessor())
                .background(RemoteSettingsOpenBridge())
                .onAppear {
                    DispatchQueue.main.async {
                        RemoteAppDelegate.schedulePlaceholderHide()
                    }
                }
        }
        .windowResizability(.contentSize)
        .commands {
            CommandMenu("원격") {
                Button("새로고침") {
                    Task { await viewModel.refresh() }
                }
                .keyboardShortcut("r", modifiers: .command)

                Divider()

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
        }
    }
}

struct RemoteSettingsOpenBridge: View {
    @Environment(\.openSettings) private var openSettings

    var body: some View {
        Color.clear
            .onReceive(NotificationCenter.default.publisher(for: .homeworkHelperRemoteOpenSettings)) { _ in
                openSettings()
            }
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
        .clipShape(RoundedRectangle(cornerRadius: RemotePopoverLayout.gameTileCornerRadius, style: .continuous))
    }

    private var fallback: some View {
        ZStack {
            RoundedRectangle(cornerRadius: RemotePopoverLayout.gameTileCornerRadius, style: .continuous)
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

enum RemotePopoverLayout {
    static let minWidth: CGFloat = 380
    static let maxWidth: CGFloat = 560
    static let width: CGFloat = minWidth
    static let rowHeight: CGFloat = 58
    static let gameIconSize: CGFloat = 34
    static let gameTileCornerRadius: CGFloat = 10
    static let gameNameFontSize: CGFloat = 18
    static let progressBadgeWidth: CGFloat = 132 * 0.90
    static let progressMeterHeight: CGFloat = 12
    static let todayBadgeWidth: CGFloat = 16
    static let statusBadgeSpacing: CGFloat = 4
    static let headerHeight: CGFloat = 28
    static let powerHeight: CGFloat = 54
    static let footerHeight: CGFloat = 34
    static let verticalPadding: CGFloat = 28
    static let verticalSpacing: CGFloat = 42
    static let pairingCTAHeight: CGFloat = 34

    static func contentWidth(processes: [RemoteProcess]) -> CGFloat {
        let longestNameCount = processes.map { $0.name.count }.max() ?? 0
        let estimatedNameWidth = min(CGFloat(longestNameCount) * 13.0, 260)
        let progressStatusClusterWidth = progressBadgeWidth + statusBadgeSpacing + todayBadgeWidth
        let rowChromeWidth = gameIconSize + 8 + progressStatusClusterWidth + gameIconSize + 34
        let visibleWidth = (NSScreen.main?.visibleFrame.width ?? 760) - 80
        let desired = max(minWidth, rowChromeWidth + max(172, estimatedNameWidth))
        return min(maxWidth, max(minWidth, min(desired, visibleWidth)))
    }

    static func contentSize(processes: [RemoteProcess], showsPairingCTA: Bool, showsSummary: Bool, incidentCount: Int) -> CGSize {
        let rows = CGFloat(max(1, processes.count))
        let pairing = showsPairingCTA ? pairingCTAHeight + 8 : 0
        let summary = showsSummary ? RemoteWindowLayout.summarySectionHeight + 8 : 0
        let incidents = incidentCount > 0 ? RemoteWindowLayout.incidentSectionHeight + 8 : 0
        let height = verticalPadding + headerHeight + verticalSpacing + (rows * rowHeight) + pairing + summary + incidents + powerHeight + footerHeight
        return CGSize(width: contentWidth(processes: processes), height: max(240, height))
    }
}

private enum MenuBarProgressVisuals {
    static func clampedPercentage(_ percentage: Double) -> Double {
        min(max(percentage, 0), 100)
    }

    static func percentageText(_ percentage: Double) -> String {
        "\(Int(clampedPercentage(percentage).rounded()))%"
    }

    static func progressTone(percentage: Double) -> Color {
        let clamped = clampedPercentage(percentage)
        if clamped <= 50 {
            return interpolatedColor(from: (0x44, 0xcc, 0x44), to: (0xff, 0xcc, 0x00), fraction: clamped / 50)
        }
        if clamped <= 80 {
            return interpolatedColor(from: (0xff, 0xcc, 0x00), to: (0xff, 0x88, 0x00), fraction: (clamped - 50) / 30)
        }
        return interpolatedColor(from: (0xff, 0x88, 0x00), to: (0xff, 0x44, 0x44), fraction: (clamped - 80) / 20)
    }

    private static func interpolatedColor(from start: (Int, Int, Int), to end: (Int, Int, Int), fraction: Double) -> Color {
        let f = min(max(fraction, 0), 1)
        let red = Double(start.0) + (Double(end.0) - Double(start.0)) * f
        let green = Double(start.1) + (Double(end.1) - Double(start.1)) * f
        let blue = Double(start.2) + (Double(end.2) - Double(start.2)) * f
        return Color(red: red / 255, green: green / 255, blue: blue / 255)
    }
}

private struct MenuBarHoverTintModifier: ViewModifier {
    let disabled: Bool
    let tint: Color

    @State private var isHovered = false

    @ViewBuilder
    func body(content: Content) -> some View {
        Group {
            if isHovered && !disabled {
                content.tint(tint)
            } else {
                content
            }
        }
        .onHover { hovering in
            guard !disabled else { return }
            withAnimation(.easeOut(duration: 0.12)) {
                isHovered = hovering
            }
        }
        .animation(.easeOut(duration: 0.12), value: isHovered)
    }
}

private extension View {
    func menuBarHoverTint(disabled: Bool = false, tint: Color = .accentColor) -> some View {
        modifier(MenuBarHoverTintModifier(disabled: disabled, tint: tint))
    }

    func menuBarSuppressFocusRing() -> some View {
        focusable(false)
    }
}

struct MenuBarGameRow: View {
    let process: RemoteProcess
    @ObservedObject var viewModel: RemoteDashboardViewModel
    let launch: () -> Void

    var body: some View {
        HStack(alignment: .center, spacing: 8) {
            GameIconView(process: process, viewModel: viewModel, preferredSize: 256, displaySize: RemotePopoverLayout.gameIconSize)
                .frame(width: RemotePopoverLayout.gameIconSize, height: RemotePopoverLayout.gameIconSize)
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 5) {
                    Text(process.name)
                        .font(.system(size: RemotePopoverLayout.gameNameFontSize, weight: .bold, design: .rounded))
                        .lineLimit(1)
                        .allowsTightening(true)
                        .truncationMode(.tail)
                        .layoutPriority(1)
                    Spacer(minLength: 4)
                    MenuBarGameStatusBadges(process: process, progress: process.progress, viewModel: viewModel)
                        .layoutPriority(2)
                        .help(viewModel.processRuntimeHelp(process))
                }
                if let progress = process.progress {
                    HStack(spacing: 5) {
                        ResourceIconView(process: process, viewModel: viewModel, preferredSize: 128, displaySize: 12)
                            .frame(width: 12, height: 12)
                        MenuBarProgressMeter(progress: progress)
                    }
                } else {
                    Text(viewModel.processStatusText(process))
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }
            MenuBarLaunchButton(launch: launch, disabled: !viewModel.isLaunchEnabled(process))
        }
        .frame(height: RemotePopoverLayout.rowHeight, alignment: .center)
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct MenuBarLaunchButton: View {
    let launch: () -> Void
    let disabled: Bool

    @State private var isHovered = false

    var body: some View {
        let active = isHovered && !disabled

        Button(action: launch) {
            ZStack {
                RoundedRectangle(cornerRadius: RemotePopoverLayout.gameTileCornerRadius, style: .continuous)
                    .fill(disabled ? Color.secondary.opacity(0.12) : Color.accentColor.opacity(active ? 1.0 : 0.86))
                    .overlay(
                        RoundedRectangle(cornerRadius: RemotePopoverLayout.gameTileCornerRadius, style: .continuous)
                            .stroke(Color.white.opacity(disabled ? 0.08 : active ? 0.42 : 0.26), lineWidth: 0.8)
                    )
                Image(systemName: "play.fill")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(disabled ? Color.secondary.opacity(0.65) : Color.white)
            }
            .frame(width: RemotePopoverLayout.gameIconSize, height: RemotePopoverLayout.gameIconSize)
        }
        .buttonStyle(.plain)
        .frame(width: RemotePopoverLayout.gameIconSize, height: RemotePopoverLayout.gameIconSize)
        .clipShape(RoundedRectangle(cornerRadius: RemotePopoverLayout.gameTileCornerRadius, style: .continuous))
        .contentShape(RoundedRectangle(cornerRadius: RemotePopoverLayout.gameTileCornerRadius, style: .continuous))
        .menuBarSuppressFocusRing()
        .onHover { hovering in
            guard !disabled else { return }
            withAnimation(.easeOut(duration: 0.12)) {
                isHovered = hovering
            }
        }
        .animation(.easeOut(duration: 0.12), value: isHovered)
        .help("실행")
        .disabled(disabled)
    }
}

struct MenuBarProgressMeter: View {
    let progress: RemoteProcess.Progress

    private var fraction: CGFloat {
        CGFloat(MenuBarProgressVisuals.clampedPercentage(progress.percentage) / 100)
    }

    var body: some View {
        GeometryReader { proxy in
            ZStack(alignment: .leading) {
                Capsule()
                    .fill(Color.secondary.opacity(0.14))
                Capsule()
                    .fill(Color.accentColor.opacity(0.72))
                    .frame(width: proxy.size.width * fraction)
                Text(MenuBarProgressVisuals.percentageText(progress.percentage))
                    .font(.system(size: 8.5, weight: .bold, design: .rounded))
                    .monospacedDigit()
                    .foregroundStyle(.white)
                    .shadow(color: Color.black.opacity(0.38), radius: 1, y: 0.5)
                    .frame(width: proxy.size.width, height: proxy.size.height, alignment: .center)
            }
        }
        .frame(maxWidth: .infinity)
        .frame(height: RemotePopoverLayout.progressMeterHeight)
        .clipShape(Capsule())
        .remoteGlass(.pill, tint: Color.accentColor.opacity(0.08))
        .accessibilityLabel("진행률 \(MenuBarProgressVisuals.percentageText(progress.percentage))")
        .help(MenuBarProgressVisuals.percentageText(progress.percentage))
    }
}

struct MenuBarRunningBadge: View {
    var body: some View {
        Text("실행 중")
            .font(.caption2.bold())
            .foregroundStyle(.green)
            .lineLimit(1)
            .minimumScaleFactor(0.72)
            .allowsTightening(true)
            .multilineTextAlignment(.center)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .frame(width: RemotePopoverLayout.progressBadgeWidth, alignment: .center)
            .remoteGlass(.pill, tint: Color.green.opacity(0.18))
            .help("실행 중")
    }
}

struct MenuBarProgressBadge: View {
    let progress: RemoteProcess.Progress
    @ObservedObject var viewModel: RemoteDashboardViewModel

    private var tone: Color {
        MenuBarProgressVisuals.progressTone(percentage: progress.percentage)
    }

    var body: some View {
        Text(viewModel.progressDisplayText(progress))
            .font(.caption2.weight(.semibold))
            .foregroundStyle(tone)
            .lineLimit(1)
            .minimumScaleFactor(0.72)
            .allowsTightening(true)
            .multilineTextAlignment(.center)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .frame(width: RemotePopoverLayout.progressBadgeWidth, alignment: .center)
            .remoteGlass(.pill, tint: tone.opacity(0.15))
            .help(viewModel.progressDisplayText(progress))
    }
}

struct MenuBarGameStatusBadges: View {
    let process: RemoteProcess
    let progress: RemoteProcess.Progress?
    @ObservedObject var viewModel: RemoteDashboardViewModel

    var body: some View {
        HStack(spacing: RemotePopoverLayout.statusBadgeSpacing) {
            if viewModel.isProcessRunningCurrent(process) {
                MenuBarRunningBadge()
            } else if let progress {
                MenuBarProgressBadge(progress: progress, viewModel: viewModel)
            }
            Label("오늘", systemImage: process.playedToday ? "checkmark.circle.fill" : "circle")
                .labelStyle(.iconOnly)
                .font(.caption2)
                .foregroundStyle(process.playedToday ? .blue : .secondary.opacity(0.55))
                .frame(width: RemotePopoverLayout.todayBadgeWidth, alignment: .center)
        }
        .fixedSize(horizontal: true, vertical: false)
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
                    ForEach(viewModel.processes) { process in
                        MenuBarGameRow(process: process, viewModel: viewModel) {
                            Task { await viewModel.launch(process) }
                        }
                    }
                    if viewModel.processes.isEmpty {
                        Text("캐시된 게임 상태가 없습니다.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .frame(height: RemotePopoverLayout.rowHeight)
                    }
                }
                if !viewModel.isPaired {
                    Button {
                        RemoteAppDelegate.openSettingsWindow()
                    } label: {
                        Label("페어링 필요 · 설정 열기", systemImage: "link.badge.plus")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.glassProminent)
                    .menuBarHoverTint()
                    .menuBarSuppressFocusRing()
                    .controlSize(.small)
                }
                if viewModel.showPlaySummary, let summary = viewModel.dashboardSummary {
                    PlaySummaryView(summary: summary)
                }
                if !viewModel.beholderIncidents.isEmpty {
                    BeholderIncidentSummaryView(incidents: viewModel.beholderIncidents)
                }
                HStack(spacing: 8) {
                    MenuBarPowerButton(action: "wake", label: "전원 켜기", systemImage: "power", viewModel: viewModel)
                    MenuBarPowerButton(action: "sleep", label: "절전", systemImage: "moon.fill", viewModel: viewModel)
                    MenuBarPowerButton(action: "restart", label: "재시동", systemImage: "arrow.clockwise", viewModel: viewModel)
                    MenuBarPowerButton(action: "shutdown", label: "시스템 종료", systemImage: "power.circle", viewModel: viewModel)
                }
                .frame(height: RemotePopoverLayout.powerHeight)
                Divider()
                HStack(spacing: 8) {
                    MenuBarFooterButton(title: "설정", systemImage: "gearshape") {
                        RemoteAppDelegate.openSettingsWindow()
                    }
                    MenuBarFooterButton(title: "새로고침", systemImage: "arrow.clockwise") {
                        Task { await viewModel.refresh() }
                    }
                    MenuBarFooterButton(title: "앱 종료", systemImage: "power") {
                        NSApp.terminate(nil)
                    }
                }
                .frame(height: 34)
            }
            .padding(14)
            .remoteGlass(.popover, variant: viewModel.popoverGlassTransparency.glass)
            .buttonStyle(.glass)
            .frame(width: RemotePopoverLayout.contentWidth(processes: viewModel.processes) - 20)
        }
    }
}

struct MenuBarPowerButton: View {
    let action: String
    let label: String
    let systemImage: String
    @ObservedObject var viewModel: RemoteDashboardViewModel

    var body: some View {
        let disabled = viewModel.isLoading || !viewModel.isPowerActionEnabled(action)

        Button {
            Task { await viewModel.power(action) }
        } label: {
            VStack(spacing: 3) {
                Image(systemName: systemImage)
                    .font(.caption)
                Text(label)
                    .font(.caption2)
                    .lineLimit(1)
                    .minimumScaleFactor(0.72)
            }
            .frame(maxWidth: .infinity, minHeight: 46)
        }
        .controlSize(.small)
        .menuBarHoverTint(disabled: disabled)
        .menuBarSuppressFocusRing()
        .disabled(disabled)
        .help(label)
    }
}

struct MenuBarFooterButton: View {
    let title: LocalizedStringKey
    let systemImage: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Label(title, systemImage: systemImage)
                .lineLimit(1)
                .frame(maxWidth: .infinity, minHeight: 30)
        }
        .controlSize(.small)
        .foregroundStyle(.primary)
        .menuBarHoverTint()
        .menuBarSuppressFocusRing()
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

enum RemoteSettingsTab: String, CaseIterable, Hashable {
    case connection
    case power
    case devices
    case android
    case app
}

enum RemoteSettingsLayout {
    static let contentWidth: CGFloat = 392
    static let tabPadding: CGFloat = 12
    static let sectionSpacing: CGFloat = 12
    static let windowHorizontalInset: CGFloat = 34
    static let windowVerticalInset: CGFloat = 72
    static let minWindowWidth: CGFloat = 430
    static let maxWindowWidth: CGFloat = 480
    static let minWindowHeight: CGFloat = 180
}

struct RemoteSettingsContentSizePreferenceKey: PreferenceKey {
    static var defaultValue: [RemoteSettingsTab: CGSize] = [:]

    static func reduce(value: inout [RemoteSettingsTab: CGSize], nextValue: () -> [RemoteSettingsTab: CGSize]) {
        value.merge(nextValue(), uniquingKeysWith: { _, new in new })
    }
}

struct RemoteSettingsView: View {
    @ObservedObject var viewModel: RemoteDashboardViewModel
    @State private var selectedTab: RemoteSettingsTab = .connection
    @State private var measuredSizes: [RemoteSettingsTab: CGSize] = [:]

    private var targetSize: CGSize {
        let measured = measuredSizes[selectedTab] ?? CGSize(width: RemoteSettingsLayout.contentWidth, height: 260)
        let paddedWidth = measured.width * 1.06 + RemoteSettingsLayout.windowHorizontalInset
        let paddedHeight = measured.height * 1.10 + RemoteSettingsLayout.windowVerticalInset
        let visible = NSScreen.main?.visibleFrame.size ?? CGSize(width: 1180, height: 800)
        return CGSize(
            width: min(RemoteSettingsLayout.maxWindowWidth, min(max(RemoteSettingsLayout.minWindowWidth, paddedWidth), max(RemoteSettingsLayout.minWindowWidth, visible.width - 80))),
            height: min(max(RemoteSettingsLayout.minWindowHeight, paddedHeight), max(RemoteSettingsLayout.minWindowHeight, visible.height - 80))
        )
    }

    var body: some View {
        GlassEffectContainer(spacing: 12) {
            TabView(selection: $selectedTab) {
                settingsConnectionTab
                    .tabItem { Label("연결", systemImage: "link") }
                    .tag(RemoteSettingsTab.connection)
                settingsPowerTab
                    .tabItem { Label("전원", systemImage: "bolt") }
                    .tag(RemoteSettingsTab.power)
                settingsDevicesTab
                    .tabItem { Label("기기", systemImage: "display.2") }
                    .tag(RemoteSettingsTab.devices)
                settingsAndroidTab
                    .tabItem { Label("Android", systemImage: "app.connected.to.app.below.fill") }
                    .tag(RemoteSettingsTab.android)
                settingsAppTab
                    .tabItem { Label("앱", systemImage: "gearshape") }
                    .tag(RemoteSettingsTab.app)
            }
            .remoteGlass(.settings)
        }
        .padding()
        .frame(width: targetSize.width, height: targetSize.height)
        .background(RemoteSettingsWindowAccessor(targetSize: targetSize))
        .background(RemoteSettingsKeyboardShortcutBridge())
        .onPreferenceChange(RemoteSettingsContentSizePreferenceKey.self) { measuredSizes = $0 }
        .onExitCommand { NSApp.keyWindow?.orderOut(nil) }
        .buttonStyle(.glass)
    }

    private var settingsConnectionTab: some View {
        SettingsTabScrollView(tab: .connection) {
            RemoteSettingsSection("연결/페어링") {
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
                    SettingsActionGrid {
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

            RemoteSettingsSection("Tailscale") {
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
        SettingsTabScrollView(tab: .power) {
            RemoteSettingsSection("전원/SSH/SmartThings") {
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
                    SettingsActionGrid {
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
                                "authorized_keys: \(setup.effectiveAuthorizedKeysPath ?? setup.authorizedKeysPath)",
                                "SSH scope: \(setup.authorizedKeysScope ?? "user")\(setup.administratorsAuthorizedKeysActive == true ? " / Administrators" : "")",
                                "SmartThings CLI: \(setup.smartthingsCLICandidates.first ?? "감지 안 됨")"
                            ]
                        )
                    }
                    if let key = viewModel.localSSHKey {
                        SidebarInfoRow(label: "로컬 SSH key", value: "\(key.privateKeyPath) · \(key.created ? "새로 생성" : "기존 사용")")
                    }
                    SidebarInfoRow(label: "SSH health", value: viewModel.localSSHHealthSummary)
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
        SettingsTabScrollView(tab: .devices) {
            RemoteSettingsSection("기기 관리") {
                VStack(alignment: .leading, spacing: 8) {
                    SettingsActionGrid {
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
        SettingsTabScrollView(tab: .android) {
            RemoteSettingsSection("Android-PC 연결") {
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
        SettingsTabScrollView(tab: .app) {
            RemoteSettingsSection("앱 동작") {
                VStack(alignment: .leading, spacing: 10) {
                    Toggle("로그인 시 실행", isOn: Binding(
                        get: { viewModel.launchAtLoginEnabled },
                        set: { enabled in viewModel.setLaunchAtLogin(enabled) }
                    ))
                    Toggle("로그인 자동 실행 시 창 표시", isOn: $viewModel.loginLaunchShowsWindow)
                    Toggle("플레이 요약 표시", isOn: $viewModel.showPlaySummary)
                    HStack {
                        Text("상태 동기화 주기")
                        Spacer()
                        TextField("초", value: $viewModel.mirrorPollIntervalSeconds, format: .number)
                            .textFieldStyle(.roundedBorder)
                            .frame(width: 58)
                        Text("초")
                            .foregroundStyle(.secondary)
                        Stepper(
                            "상태 동기화 주기",
                            value: $viewModel.mirrorPollIntervalSeconds,
                            in: 1...60,
                            step: 1
                        )
                        .labelsHidden()
                    }
                    Text("1~60초 사이에서 1초 단위로 조정합니다. 기본값은 5초입니다.")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                    Picker("비 HoYoLab 진행률 표시", selection: $viewModel.cycleProgressDisplayMode) {
                        ForEach(CycleProgressDisplayMode.allCases) { mode in
                            Text(mode.label).tag(mode)
                        }
                    }
                    .pickerStyle(.segmented)
                    Picker("Popover 투명도", selection: $viewModel.popoverGlassTransparency) {
                        ForEach(RemotePopoverGlassTransparency.allCases) { option in
                            Text(option.label).tag(option)
                        }
                    }
                    .pickerStyle(.segmented)
                    Text(viewModel.popoverGlassTransparency.description)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
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
    let tab: RemoteSettingsTab
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: RemoteSettingsLayout.sectionSpacing) {
            content
        }
        .frame(width: RemoteSettingsLayout.contentWidth, alignment: .topLeading)
        .fixedSize(horizontal: false, vertical: true)
        .padding(RemoteSettingsLayout.tabPadding)
        .background(
            GeometryReader { proxy in
                Color.clear.preference(
                    key: RemoteSettingsContentSizePreferenceKey.self,
                    value: [tab: proxy.size]
                )
            }
        )
        .frame(maxWidth: .infinity, alignment: .top)
    }
}

struct RemoteSettingsSection<Content: View>: View {
    private let title: LocalizedStringKey
    private let content: Content

    init(_ title: LocalizedStringKey, @ViewBuilder content: () -> Content) {
        self.title = title
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.headline)
            content
        }
        .padding(.vertical, 4)
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct SettingsActionGrid<Content: View>: View {
    private let content: Content
    private let columns = [
        GridItem(.adaptive(minimum: 126), spacing: 8, alignment: .leading)
    ]

    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    var body: some View {
        LazyVGrid(columns: columns, alignment: .leading, spacing: 8) {
            content
        }
        .frame(maxWidth: .infinity, alignment: .leading)
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
    var systemImage = "info.circle"

    var body: some View {
        HStack(alignment: .center, spacing: 8) {
            Image(systemName: systemImage)
                .frame(width: 16)
                .foregroundStyle(.secondary)
            VStack(alignment: .leading, spacing: 1) {
                Text(label)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                Text(value)
                    .font(.caption)
                    .lineLimit(1)
                    .textSelection(.enabled)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
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
