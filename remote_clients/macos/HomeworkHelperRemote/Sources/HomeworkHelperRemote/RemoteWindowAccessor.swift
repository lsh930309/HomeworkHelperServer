import AppKit
import SwiftUI

enum RemoteWindowLayout {
    static let sidebarWidth: CGFloat = 278
    static let dividerWidth: CGFloat = 1
    static let mainContentInset: CGFloat = 18
    static let sidebarInset: CGFloat = 22
    static let sectionInset: CGFloat = 14
    static let horizontalPadding: CGFloat = mainContentInset * 2
    static let glassOuterInset: CGFloat = 0
    static let glassHaloAllowance: CGFloat = 0
    static let titlebarReserveHeight: CGFloat = 0
    static let titlebarContentInset: CGFloat = 28
    static let windowCornerRadius: CGFloat = 28
    static let headerHeight: CGFloat = 72
    static let gameSectionHeight: CGFloat = 192
    static let summarySectionHeight: CGFloat = 154
    static let incidentSectionHeight: CGFloat = 92
    static let gameCardWidth: CGFloat = 180
    static let gameCardHeight: CGFloat = 126
    static let gameCardSpacing: CGFloat = 12
    static let minWindowWidth: CGFloat = 720
    static let compactWindowHeight: CGFloat = 326
    static let sidebarMinimumHeight: CGFloat = 386
    static let fallbackMaxWindowSize = CGSize(width: 1180, height: 720)

    static func maxWindowSize() -> CGSize {
        guard let frame = NSScreen.main?.visibleFrame else { return fallbackMaxWindowSize }
        return CGSize(
            width: min(fallbackMaxWindowSize.width, max(minWindowWidth, frame.width - 24)),
            height: min(fallbackMaxWindowSize.height, max(compactWindowHeight, frame.height - 24))
        )
    }

    static func gameViewportWidth(cardCount: Int) -> CGFloat {
        let visibleCards = max(1, min(cardCount, 4))
        let cards = CGFloat(visibleCards)
        return cards * gameCardWidth + max(0, cards - 1) * gameCardSpacing
    }

    static func gameContentWidth(cardCount: Int) -> CGFloat {
        let cards = CGFloat(max(1, cardCount))
        return cards * gameCardWidth + max(0, cards - 1) * gameCardSpacing
    }

    static func mainColumnWidth(cardCount: Int) -> CGFloat {
        gameViewportWidth(cardCount: cardCount) + (sectionInset * 2)
    }

    static func mainContentWidth(cardCount: Int) -> CGFloat {
        mainColumnWidth(cardCount: cardCount) + horizontalPadding
    }

    static func contentSize(cardCount: Int, sidebarVisible: Bool, hasSummary: Bool, hasIncidents: Bool) -> CGSize {
        let maxSize = maxWindowSize()
        let sidebar = sidebarVisible ? sidebarWidth + dividerWidth : 0
        let shellHorizontalInset = (glassOuterInset + glassHaloAllowance) * 2
        let rawWidth = sidebar + mainContentWidth(cardCount: cardCount) + shellHorizontalInset
        let contentSpacing: CGFloat = 12
        let baseHeight = mainContentInset + headerHeight + contentSpacing + gameSectionHeight
        let summaryHeight = hasSummary ? contentSpacing + summarySectionHeight : 0
        let incidentHeight = hasIncidents ? contentSpacing + incidentSectionHeight : 0
        let contentHeight = baseHeight + summaryHeight + incidentHeight
        let sidebarHeight = sidebarVisible ? sidebarMinimumHeight : 0
        let shellVerticalInset = titlebarContentInset + titlebarReserveHeight + glassOuterInset + glassHaloAllowance
        let rawHeight = max(contentHeight, sidebarHeight) + shellVerticalInset
        return CGSize(
            width: min(maxSize.width, max(minWindowWidth, rawWidth)),
            height: min(maxSize.height, max(compactWindowHeight, rawHeight))
        )
    }

}

final class RemoteWindowDelegate: NSObject, NSWindowDelegate {
    static let shared = RemoteWindowDelegate()

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        sender.orderOut(nil)
        NSApp.setActivationPolicy(.accessory)
        return false
    }
}

struct RemoteWindowAccessor: NSViewRepresentable {
    let cardCount: Int
    let sidebarVisible: Bool
    let hasSummary: Bool
    let hasIncidents: Bool

    func makeNSView(context: Context) -> NSView {
        let view = NSView()
        DispatchQueue.main.async { configure(window: view.window) }
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {
        DispatchQueue.main.async { configure(window: nsView.window) }
    }

    private func configure(window: NSWindow?) {
        guard let window else { return }
        let size = RemoteWindowLayout.contentSize(cardCount: cardCount, sidebarVisible: sidebarVisible, hasSummary: hasSummary, hasIncidents: hasIncidents)
        let maxSize = RemoteWindowLayout.maxWindowSize()
        window.minSize = size
        window.maxSize = maxSize
        window.setContentSize(size)
        window.styleMask = [.titled, .closable, .miniaturizable, .fullSizeContentView]
        window.styleMask.remove(.resizable)
        window.delegate = RemoteWindowDelegate.shared
        window.title = ""
        window.identifier = NSUserInterfaceItemIdentifier(RemoteAppDelegate.mainWindowIdentifier)
        window.isOpaque = false
        window.backgroundColor = .clear
        window.hasShadow = true
        window.titlebarAppearsTransparent = true
        window.titleVisibility = .hidden
        window.titlebarSeparatorStyle = .none
        window.isMovableByWindowBackground = true
        window.toolbarStyle = .unified
        RemoteAppDelegate.prepareMainWindow(window)
    }
}

struct RemotePlaceholderWindowAccessor: NSViewRepresentable {
    func makeNSView(context: Context) -> NSView {
        let view = NSView()
        DispatchQueue.main.async { configure(window: view.window) }
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {
        DispatchQueue.main.async { configure(window: nsView.window) }
    }

    private func configure(window: NSWindow?) {
        guard let window else { return }
        window.identifier = NSUserInterfaceItemIdentifier(RemoteAppDelegate.placeholderWindowIdentifier)
        window.title = RemoteAppDelegate.placeholderWindowTitle
        window.alphaValue = 0
        window.ignoresMouseEvents = true
        window.setFrame(NSRect(x: -10_000, y: -10_000, width: 160, height: 96), display: false)
        window.orderOut(nil)
    }
}

struct RemoteSettingsWindowAccessor: NSViewRepresentable {
    let targetSize: CGSize

    func makeNSView(context: Context) -> NSView {
        let view = NSView()
        DispatchQueue.main.async { configure(window: view.window) }
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {
        DispatchQueue.main.async { configure(window: nsView.window) }
    }

    private func configure(window: NSWindow?) {
        guard let window else { return }
        let maxSize = NSScreen.main.map {
            CGSize(
                width: max(RemoteSettingsLayout.minWindowWidth, $0.visibleFrame.width - 80),
                height: max(RemoteSettingsLayout.minWindowHeight, $0.visibleFrame.height - 80)
            )
        } ?? CGSize(width: 1180, height: 800)
        window.minSize = CGSize(width: RemoteSettingsLayout.minWindowWidth, height: RemoteSettingsLayout.minWindowHeight)
        window.maxSize = maxSize
        window.setContentSize(targetSize)
        window.titlebarAppearsTransparent = true
        window.titleVisibility = .visible
        window.isMovableByWindowBackground = true
    }
}

struct RemoteSettingsKeyboardShortcutBridge: NSViewRepresentable {
    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeNSView(context: Context) -> NSView {
        let view = NSView()
        context.coordinator.attach(to: view)
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {
        context.coordinator.view = nsView
    }

    final class Coordinator {
        weak var view: NSView?
        private var monitor: Any?

        deinit {
            if let monitor {
                NSEvent.removeMonitor(monitor)
            }
        }

        func attach(to view: NSView) {
            self.view = view
            guard monitor == nil else { return }
            monitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
                guard let self, let window = self.view?.window, NSApp.keyWindow === window else {
                    return event
                }
                let isEscape = event.keyCode == 53
                let isReturn = event.keyCode == 36 || event.keyCode == 76
                let isCommandReturn = isReturn && event.modifierFlags.contains(.command)
                if isEscape || isCommandReturn || (isReturn && !self.isEditingText(in: window)) {
                    window.orderOut(nil)
                    return nil
                }
                return event
            }
        }

        private func isEditingText(in window: NSWindow) -> Bool {
            if window.firstResponder is NSTextView { return true }
            return String(describing: type(of: window.firstResponder as Any)).contains("FieldEditor")
        }
    }
}
