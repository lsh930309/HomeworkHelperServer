import AppKit
import SwiftUI

enum RemoteWindowLayout {
    static let sidebarWidth: CGFloat = 252
    static let dividerWidth: CGFloat = 1
    static let horizontalPadding: CGFloat = 24
    static let glassOuterInset: CGFloat = 10
    static let glassHaloAllowance: CGFloat = 6
    static let titlebarReserveHeight: CGFloat = 0
    static let gameCardWidth: CGFloat = 160
    static let gameCardHeight: CGFloat = 114
    static let gameCardSpacing: CGFloat = 10
    static let minWindowWidth: CGFloat = 720
    static let compactWindowHeight: CGFloat = 344
    static let sidebarMinimumHeight: CGFloat = 344
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

    static func mainContentWidth(cardCount: Int) -> CGFloat {
        gameViewportWidth(cardCount: cardCount) + horizontalPadding
    }

    static func contentSize(cardCount: Int, sidebarVisible: Bool, hasSummary: Bool, hasIncidents: Bool) -> CGSize {
        let maxSize = maxWindowSize()
        let sidebar = sidebarVisible ? sidebarWidth + dividerWidth : 0
        let shellHorizontalInset = (glassOuterInset + glassHaloAllowance) * 2
        let rawWidth = sidebar + mainContentWidth(cardCount: cardCount) + shellHorizontalInset
        let baseHeight: CGFloat = 284
        let summaryHeight: CGFloat = hasSummary ? 92 : 0
        let incidentHeight: CGFloat = hasIncidents ? 84 : 0
        let contentHeight = baseHeight + summaryHeight + incidentHeight
        let sidebarHeight = sidebarVisible ? sidebarMinimumHeight : 0
        let shellVerticalInset = titlebarReserveHeight + glassOuterInset + glassHaloAllowance
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
        window.styleMask.insert(.fullSizeContentView)
        window.styleMask.remove(.resizable)
        window.delegate = RemoteWindowDelegate.shared
        window.title = RemoteAppDelegate.mainWindowTitle
        window.identifier = NSUserInterfaceItemIdentifier(RemoteAppDelegate.mainWindowIdentifier)
        window.isOpaque = false
        window.backgroundColor = .clear
        window.titlebarAppearsTransparent = true
        window.titleVisibility = .hidden
        window.isMovableByWindowBackground = true
        installFrameGlassBackground(in: window)
        RemoteAppDelegate.prepareMainWindow(window)
    }

    private func installFrameGlassBackground(in window: NSWindow) {
        guard let frameView = window.contentView?.superview else { return }
        let backgroundIdentifier = NSUserInterfaceItemIdentifier("HomeworkHelperRemoteFrameGlassBackground")
        if frameView.subviews.contains(where: { $0.identifier == backgroundIdentifier }) { return }
        let glass = NSGlassEffectView()
        glass.identifier = backgroundIdentifier
        glass.cornerRadius = RemoteGlassMetrics.windowCornerRadius
        glass.clipsToBounds = false
        glass.translatesAutoresizingMaskIntoConstraints = false
        frameView.addSubview(glass, positioned: .below, relativeTo: window.contentView)
        NSLayoutConstraint.activate([
            glass.leadingAnchor.constraint(equalTo: frameView.leadingAnchor),
            glass.trailingAnchor.constraint(equalTo: frameView.trailingAnchor),
            glass.topAnchor.constraint(equalTo: frameView.topAnchor),
            glass.bottomAnchor.constraint(equalTo: frameView.bottomAnchor),
        ])
    }
}
