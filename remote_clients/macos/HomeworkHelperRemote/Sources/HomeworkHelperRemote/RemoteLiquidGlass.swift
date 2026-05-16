import AppKit
import SwiftUI

enum RemoteGlassMetrics {
    static let windowCornerRadius: CGFloat = RemoteWindowLayout.windowCornerRadius
    static let sectionCornerRadius: CGFloat = 20
    static let cardCornerRadius: CGFloat = 16
    static let pillCornerRadius: CGFloat = 999
    static let buttonCornerRadius: CGFloat = 12
}

enum RemoteGlassRole {
    case window
    case section
    case card
    case pill
    case button
    case popover
    case settings
}

struct RemoteGlassSurface: ViewModifier {
    let role: RemoteGlassRole
    var interactive = false
    var tint: Color? = nil

    func body(content: Content) -> some View {
        content.glassEffect(glass, in: RoundedRectangle(cornerRadius: radius, style: .continuous))
    }

    private var radius: CGFloat {
        switch role {
        case .window:
            return RemoteGlassMetrics.windowCornerRadius
        case .section, .settings, .popover:
            return RemoteGlassMetrics.sectionCornerRadius
        case .card:
            return RemoteGlassMetrics.cardCornerRadius
        case .button:
            return RemoteGlassMetrics.buttonCornerRadius
        case .pill:
            return RemoteGlassMetrics.pillCornerRadius
        }
    }

    private var glass: Glass {
        Glass.regular
            .tint(tint)
            .interactive(interactive)
    }
}

extension View {
    func remoteGlass(_ role: RemoteGlassRole, interactive: Bool = false, tint: Color? = nil) -> some View {
        modifier(RemoteGlassSurface(role: role, interactive: interactive, tint: tint))
    }
}

struct RemoteGlassGroupBox<Label: View, Content: View>: View {
    private let label: Label
    private let content: Content

    init(_ title: LocalizedStringKey, @ViewBuilder content: () -> Content) where Label == Text {
        self.label = Text(title)
        self.content = content()
    }

    init(@ViewBuilder content: () -> Content, @ViewBuilder label: () -> Label) {
        self.label = label()
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            label
                .font(.headline)
            content
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .remoteGlass(.section)
    }
}

final class RemoteHitTestShieldView: NSView {
    override var acceptsFirstResponder: Bool { true }

    override func hitTest(_ point: NSPoint) -> NSView? {
        bounds.contains(point) ? self : nil
    }
}

struct RemoteWindowHitTestShield: NSViewRepresentable {
    func makeNSView(context: Context) -> RemoteHitTestShieldView {
        let view = RemoteHitTestShieldView()
        view.translatesAutoresizingMaskIntoConstraints = false
        view.wantsLayer = true
        view.layer?.backgroundColor = NSColor.clear.cgColor
        return view
    }

    func updateNSView(_ nsView: RemoteHitTestShieldView, context: Context) {}
}

struct RemoteAppKitLiquidGlassBackground: NSViewRepresentable {
    func makeNSView(context: Context) -> NSGlassEffectContainerView {
        let container = NSGlassEffectContainerView()
        let glass = NSGlassEffectView()
        glass.cornerRadius = 0
        glass.clipsToBounds = false
        glass.translatesAutoresizingMaskIntoConstraints = false
        container.addSubview(glass)
        NSLayoutConstraint.activate([
            glass.leadingAnchor.constraint(equalTo: container.leadingAnchor),
            glass.trailingAnchor.constraint(equalTo: container.trailingAnchor),
            glass.topAnchor.constraint(equalTo: container.topAnchor),
            glass.bottomAnchor.constraint(equalTo: container.bottomAnchor),
        ])
        return container
    }

    func updateNSView(_ container: NSGlassEffectContainerView, context: Context) {
        for glass in container.subviews.compactMap({ $0 as? NSGlassEffectView }) {
            glass.cornerRadius = 0
            glass.clipsToBounds = false
        }
    }
}
