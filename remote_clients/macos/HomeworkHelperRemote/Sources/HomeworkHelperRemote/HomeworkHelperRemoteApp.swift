import SwiftUI
import AppKit

extension Notification.Name {
    static let homeworkHelperRemoteMainWindowWillShow = Notification.Name("HomeworkHelperRemoteMainWindowWillShow")
    static let homeworkHelperRemoteToggleSidebar = Notification.Name("HomeworkHelperRemoteToggleSidebar")
    static let homeworkHelperRemoteRefreshRequested = Notification.Name("HomeworkHelperRemoteRefreshRequested")
    static let homeworkHelperRemoteOpenSettings = Notification.Name("HomeworkHelperRemoteOpenSettings")
    static let homeworkHelperRemoteMenuBarIconDidChange = Notification.Name("HomeworkHelperRemoteMenuBarIconDidChange")
    static let homeworkHelperRemoteMenuBarStatusDidChange = Notification.Name("HomeworkHelperRemoteMenuBarStatusDidChange")
    static let homeworkHelperRemoteGlobalShortcutPressed = Notification.Name("HomeworkHelperRemoteGlobalShortcutPressed")
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
    private var popoverOutsideClickMonitor: Any?
    private let popover = NSPopover()

    func applicationDidFinishLaunching(_ notification: Notification) {
        Self.shared = self
        NSApp.setActivationPolicy(.accessory)
        configureStatusItem()
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(menuBarIconDidChange(_:)),
            name: .homeworkHelperRemoteMenuBarIconDidChange,
            object: nil
        )
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(menuBarStatusDidChange(_:)),
            name: .homeworkHelperRemoteMenuBarStatusDidChange,
            object: nil
        )
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(globalShortcutPressed(_:)),
            name: .homeworkHelperRemoteGlobalShortcutPressed,
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
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        false
    }

    func applicationWillTerminate(_ notification: Notification) {
        removeStatusItemClickMonitor()
        removePopoverOutsideClickMonitor()
        NotificationCenter.default.removeObserver(self)
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showPopoverFromStatusItem()
        return true
    }

    private func configureStatusItem() {
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        configureStatusButton(item.button)
        item.button?.target = self
        item.button?.action = #selector(RemoteAppDelegate.statusItemClicked(_:))
        item.button?.sendAction(on: [.leftMouseDown])
        item.button?.isEnabled = true
        statusItem = item
        installStatusItemClickMonitor()

        popover.behavior = .transient
        popover.delegate = self
        popover.contentViewController = Self.makePopoverController()
        updatePopoverContentSize()
    }

    private func configureStatusButton(_ button: NSStatusBarButton?) {
        guard let button else { return }
        let viewModel = RemoteSharedModel.viewModel
        let state = viewModel.menuBarPresentationState()
        let symbol = viewModel.menuBarIconSymbol(for: state)
        if let image = NSImage(systemSymbolName: symbol, accessibilityDescription: "HomeworkHelper Remote") {
            image.isTemplate = true
            button.image = image
            button.title = ""
        } else {
            button.image = nil
            button.title = "HH"
        }
        button.imagePosition = .imageOnly
        button.toolTip = state.tooltip
    }

    @objc func statusItemClicked(_ sender: Any?) {
        guard let button = sender as? NSStatusBarButton ?? statusItem?.button else {
            Self.openSettingsWindow()
            return
        }
        scheduleStatusItemToggle(relativeTo: button)
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
            self.scheduleStatusItemToggle(relativeTo: button)
            return nil
        }
    }

    private func removeStatusItemClickMonitor() {
        if let monitor = statusItemClickMonitor {
            NSEvent.removeMonitor(monitor)
            statusItemClickMonitor = nil
        }
    }

    private func installPopoverOutsideClickMonitor() {
        guard popoverOutsideClickMonitor == nil else { return }
        popoverOutsideClickMonitor = NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown]) { [weak self] _ in
            Task { @MainActor in
                self?.closePopoverForFocusLoss()
            }
        }
    }

    private func removePopoverOutsideClickMonitor() {
        if let monitor = popoverOutsideClickMonitor {
            NSEvent.removeMonitor(monitor)
            popoverOutsideClickMonitor = nil
        }
    }

    func applicationDidResignActive(_ notification: Notification) {
        closePopoverForFocusLoss()
    }

    func popoverDidClose(_ notification: Notification) {
        removePopoverOutsideClickMonitor()
        NSApp.setActivationPolicy(.accessory)
    }

    private func closePopoverForFocusLoss() {
        guard popover.isShown else {
            removePopoverOutsideClickMonitor()
            return
        }
        popover.performClose(nil)
        removePopoverOutsideClickMonitor()
    }

    private func scheduleStatusItemToggle(relativeTo button: NSStatusBarButton) {
        DispatchQueue.main.async { [weak self, weak button] in
            guard let self, let button else { return }
            self.togglePopover(relativeTo: button)
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
            processes: RemoteSharedModel.viewModel.displayProcesses,
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
            closePopoverForFocusLoss()
            return
        }
        showPopover(relativeTo: button)
    }

    private func showPopover(relativeTo button: NSStatusBarButton) {
        updatePopoverContentSize()
        NSApp.setActivationPolicy(.accessory)
        NSApp.activate(ignoringOtherApps: true)
        installPopoverOutsideClickMonitor()
        popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
        DispatchQueue.main.async { [weak self] in
            self?.focusPopoverWindow()
        }
    }

    private func focusPopoverWindow() {
        guard popover.isShown,
              let window = popover.contentViewController?.view.window else {
            return
        }
        NSApp.activate(ignoringOtherApps: true)
        window.makeKeyAndOrderFront(nil)
    }

    @objc private func menuBarIconDidChange(_ notification: Notification) {
        configureStatusButton(statusItem?.button)
    }

    @objc private func menuBarStatusDidChange(_ notification: Notification) {
        configureStatusButton(statusItem?.button)
    }

    @objc private func globalShortcutPressed(_ notification: Notification) {
        showPopoverFromStatusItem()
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
            processes: RemoteSharedModel.viewModel.displayProcesses,
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
        shared?.closePopoverForFocusLoss()
        NSApp.setActivationPolicy(.accessory)
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

                Button("설정…") {
                    RemoteAppDelegate.openSettingsWindow()
                }
                .keyboardShortcut(",", modifiers: .command)
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
        .overlay { runningOverlay }
        .overlay(alignment: .topTrailing) {
            playNeededDotOverlay
        }
        .help(viewModel.processRuntimeHelp(process))
    }

    @ViewBuilder
    private var runningOverlay: some View {
        if viewModel.isProcessRunningCurrent(process) {
            RoundedRectangle(cornerRadius: RemotePopoverLayout.gameTileCornerRadius, style: .continuous)
                .stroke(Color.green, lineWidth: Swift.max(2, displaySize * 0.06))
                .shadow(color: Color.green.opacity(0.38), radius: Swift.max(2, displaySize * 0.08))
        }
    }

    @ViewBuilder
    private var playNeededDotOverlay: some View {
        if !process.playedToday {
            Circle()
                .fill(Color.red)
                .frame(width: playNeededDotSize, height: playNeededDotSize)
                .overlay(Circle().stroke(Color.white.opacity(0.92), lineWidth: playNeededDotStrokeWidth))
                .shadow(color: Color.black.opacity(0.18), radius: 1, y: 0.5)
                .offset(x: playNeededDotOffset, y: -playNeededDotOffset)
        }
    }

    private var playNeededDotSize: CGFloat { Swift.max(7, displaySize * 0.22) }
    private var playNeededDotStrokeWidth: CGFloat { Swift.max(1.2, displaySize * 0.035) }
    private var playNeededDotOffset: CGFloat { Swift.max(1, displaySize * 0.04) }

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
            Text(viewModel.trackBadgeDisplayText(progress))
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

    static func progressTone(percentage: Double) -> Color {
        let clamped = clampedPercentage(percentage)
        let hue = (1.0 - (clamped / 100.0)) * 0.33
        return Color(hue: hue, saturation: 0.76, brightness: 0.86)
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
                    MenuBarGameStatusBadges(progress: process.progress, viewModel: viewModel)
                        .layoutPriority(2)
                        .help(viewModel.processRuntimeHelp(process))
                }
                if let progress = process.progress {
                    HStack(spacing: 5) {
                        ResourceIconView(process: process, viewModel: viewModel, preferredSize: 128, displaySize: 12)
                            .frame(width: 12, height: 12)
                        MenuBarProgressMeter(progress: progress, viewModel: viewModel)
                    }
                } else {
                    Text(viewModel.processStatusText(process))
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }
            MenuBarLaunchButton(launch: launch, disabled: !viewModel.isLaunchEnabled(process), isPending: viewModel.isLaunchPending(process))
        }
        .frame(height: RemotePopoverLayout.rowHeight, alignment: .center)
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct MenuBarLaunchButton: View {
    let launch: () -> Void
    let disabled: Bool
    let isPending: Bool

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
                Image(systemName: isPending ? "hourglass" : "play.fill")
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
        .help(isPending ? "실행 확인 중" : "실행")
        .disabled(disabled)
    }
}

struct MenuBarProgressMeter: View {
    let progress: RemoteProcess.Progress
    @ObservedObject var viewModel: RemoteDashboardViewModel

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
                Text(viewModel.progressMeterDisplayText(progress))
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
        .accessibilityLabel("진행률 \(viewModel.progressMeterDisplayText(progress))")
        .help(viewModel.progressMeterDisplayText(progress))
    }
}

struct MenuBarProgressBadge: View {
    let progress: RemoteProcess.Progress
    @ObservedObject var viewModel: RemoteDashboardViewModel

    private var tone: Color {
        MenuBarProgressVisuals.progressTone(percentage: progress.percentage)
    }

    var body: some View {
        Text(viewModel.trackBadgeDisplayText(progress))
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
            .help(viewModel.trackBadgeDisplayText(progress))
    }
}

struct MenuBarGameStatusBadges: View {
    let progress: RemoteProcess.Progress?
    @ObservedObject var viewModel: RemoteDashboardViewModel

    var body: some View {
        HStack(spacing: RemotePopoverLayout.statusBadgeSpacing) {
            if let progress {
                MenuBarProgressBadge(progress: progress, viewModel: viewModel)
            }
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
                    ForEach(viewModel.displayProcesses) { process in
                        MenuBarGameRow(process: process, viewModel: viewModel) {
                            Task { await viewModel.launch(process) }
                        }
                    }
                    if viewModel.displayProcesses.isEmpty {
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
            .frame(width: RemotePopoverLayout.contentWidth(processes: viewModel.displayProcesses) - 20)
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
                    SettingsActionGrid {
                        Button("Tailscale 기반환경 활성화") { Task { await viewModel.activateLocalTailscale() } }
                            .disabled(viewModel.isLoading)
                        Button("Tailscale 서버/호스트 탐색") { Task { await viewModel.discoverTailscale() } }
                            .disabled(viewModel.isLoading)
                        Button("Tailscale 네트워크 비활성화", role: .destructive) { Task { await viewModel.deactivateLocalTailscale() } }
                            .disabled(viewModel.isLoading)
                    }
                    if let local = viewModel.localTailscale {
                        SidebarInfoRow(label: "기반환경", value: local.foundationState)
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
            RemoteSettingsSection("전원 자동 설정") {
                VStack(alignment: .leading, spacing: 8) {
                    Text("Wake는 Mac 로컬 SmartThings CLI가, 절전/종료/재시동은 Mac 로컬 OpenSSH key가 직접 수행합니다. 호스트에는 key 등록/준비 상태만 자동 확인합니다.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    SidebarInfoRow(
                        label: "Wake 대상",
                        value: viewModel.powerConfig.smartthingsDeviceID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                            ? "PC 켜기 자동 탐색 대기"
                            : viewModel.powerConfig.smartthingsDeviceID
                    )
                    SidebarInfoRow(
                        label: "SmartThings CLI",
                        value: LocalPowerWakeManager.resolveSmartThingsCLIPath(viewModel.powerConfig.smartthingsCLIPath)
                            ?? (viewModel.powerConfig.smartthingsCLIPath.isEmpty ? "자동 설치/확인 대기" : viewModel.powerConfig.smartthingsCLIPath)
                    )
                    SidebarInfoRow(
                        label: "SSH host",
                        value: viewModel.powerConfig.sshHost.isEmpty ? "Base URL에서 자동 설정" : "\(viewModel.powerConfig.sshHost):\(viewModel.powerConfig.sshPort)"
                    )
                    SidebarInfoRow(label: "SSH user", value: viewModel.powerConfig.sshUser.isEmpty ? "호스트 계정 자동 확인 대기" : viewModel.powerConfig.sshUser)
                    SidebarInfoRow(label: "SSH key", value: viewModel.powerConfig.normalizedLocalSSHKeyPath())
                    SettingsActionGrid {
                        Button("자동 설정 점검") { Task { await viewModel.runSetupAutomation() } }
                            .disabled(viewModel.isLoading)
                        Button("전원 준비 확인") { Task { await viewModel.refreshPowerSetup() } }
                            .disabled(!viewModel.isPaired || viewModel.isLoading)
                    }
                    if let setup = viewModel.powerSetup {
                        SetupInstructionBlock(
                            title: "호스트 SSH 준비",
                            lines: [
                                "OpenSSH: \(setup.sshService.running ? "실행 중" : "조치 필요")",
                                "Firewall: \(setup.firewall.enabled ? "SSH 허용" : "확인 필요")",
                                "authorized_keys: \(setup.effectiveAuthorizedKeysPath ?? setup.authorizedKeysPath)",
                                "SSH scope: \(setup.authorizedKeysScope ?? "user")\(setup.administratorsAuthorizedKeysActive == true ? " / Administrators" : "")"
                            ]
                        )
                    }
                    if let key = viewModel.localSSHKey {
                        SidebarInfoRow(label: "로컬 SSH key", value: "\(key.privateKeyPath) · \(key.created ? "새로 생성" : "기존 사용")")
                    }
                    SidebarInfoRow(label: "SSH health", value: viewModel.localSSHHealthSummary)
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
                        Button("현재 토큰 갱신") { Task { await viewModel.refreshToken() } }
                            .disabled(viewModel.tokenText.isEmpty || viewModel.isLoading)
                    }
                    Text("이 Mac에서는 기기 목록을 읽기 전용으로 표시합니다. 토큰 폐기와 페어링 정리는 Windows Host 원격 설정에서만 수행할 수 있습니다.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    ForEach(viewModel.sortedDevices) { device in
                        HStack {
                            VStack(alignment: .leading) {
                                Text(device.name)
                                    .foregroundStyle(viewModel.isCurrentDevice(device) ? .secondary : .primary)
                                Text(viewModel.deviceSubtitle(device))
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                            Spacer()
                            VStack(alignment: .trailing, spacing: 2) {
                                Text("페어링 \(viewModel.devicePairingDisplay(device))")
                                Text("통신 \(viewModel.deviceConnectivityDisplay(device))")
                            }
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        }
                        .opacity(viewModel.isCurrentDevice(device) ? 0.55 : 1.0)
                        .allowsHitTesting(!viewModel.isCurrentDevice(device))
                        .help(device.healthMessage ?? "")
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
                    Picker("대기 상태 아이콘", selection: $viewModel.menuBarIdleIconSymbol) {
                        ForEach(RemoteMenuBarIconChoice.symbols, id: \.self) { symbol in
                            Label(symbol, systemImage: symbol).tag(symbol)
                        }
                    }
                    .pickerStyle(.menu)
                    Picker("실행 중 아이콘", selection: $viewModel.menuBarRunningIconSymbol) {
                        ForEach(RemoteMenuBarIconChoice.symbols, id: \.self) { symbol in
                            Label(symbol, systemImage: symbol).tag(symbol)
                        }
                    }
                    .pickerStyle(.menu)
                    Picker("오프라인/Standalone 아이콘", selection: $viewModel.menuBarOfflineIconSymbol) {
                        ForEach(RemoteMenuBarIconChoice.symbols, id: \.self) { symbol in
                            Label(symbol, systemImage: symbol).tag(symbol)
                        }
                    }
                    .pickerStyle(.menu)
                    Text("상태별 내장 SF Symbols를 메뉴바 아이콘으로 사용합니다.")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                    Toggle("Popover 전역 단축키 사용", isOn: $viewModel.popoverGlobalShortcutEnabled)
                    Text(viewModel.globalShortcutStatusMessage)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }

            RemoteSettingsSection("Moonlight 원격 플레이") {
                VStack(alignment: .leading, spacing: 8) {
                    Text("이번 단계는 Moonlight 앱과 저장된 Desktop host 후보를 읽기 전용으로 감지합니다. 스트리밍 실행은 아직 수행하지 않습니다.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    SidebarInfoRow(label: "상태", value: viewModel.moonlightSnapshot.readiness.label, systemImage: "moon.stars")
                    SidebarInfoRow(label: "Moonlight", value: viewModel.moonlightInstallationDisplay, systemImage: "app")
                    SidebarInfoRow(label: "설정 파일", value: viewModel.moonlightSnapshot.preferencesReadable ? viewModel.moonlightSnapshot.preferencesPath : "읽기 실패 · \(viewModel.moonlightSnapshot.preferencesPath)", systemImage: "doc.text")
                    SidebarInfoRow(label: "선택 host", value: viewModel.moonlightSelectedHostDisplay, systemImage: "desktopcomputer")
                    SidebarInfoRow(label: "진단", value: viewModel.moonlightSnapshot.message, systemImage: "waveform.path.ecg")

                    if viewModel.moonlightSelectableHosts.count > 1 {
                        Picker("Moonlight host 선택", selection: $viewModel.selectedMoonlightHostUUID) {
                            Text("자동 감지").tag("")
                            ForEach(viewModel.moonlightSelectableHosts) { host in
                                Text("\(host.displayTitle) · \(host.uuid)").tag(host.uuid)
                            }
                        }
                        .pickerStyle(.menu)
                    }

                    if !viewModel.moonlightSnapshot.hosts.isEmpty {
                        VStack(alignment: .leading, spacing: 6) {
                            Text("감지된 host")
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                            ForEach(viewModel.moonlightSnapshot.hosts) { host in
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(host.displayTitle)
                                        .font(.caption)
                                        .fontWeight(.semibold)
                                    Text("\(host.appSummary) · \(host.addressSummary)")
                                        .font(.caption2)
                                        .foregroundStyle(.secondary)
                                        .lineLimit(2)
                                        .textSelection(.enabled)
                                }
                                .frame(maxWidth: .infinity, alignment: .leading)
                            }
                        }
                    }

                    SettingsActionGrid {
                        Button("Moonlight 설정 다시 읽기") {
                            viewModel.refreshMoonlightSnapshot()
                        }
                    }
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
