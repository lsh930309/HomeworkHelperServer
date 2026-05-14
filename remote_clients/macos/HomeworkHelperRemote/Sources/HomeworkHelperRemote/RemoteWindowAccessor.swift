import AppKit
import SwiftUI

final class RemoteWindowDelegate: NSObject, NSWindowDelegate {
    static let shared = RemoteWindowDelegate()

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        sender.orderOut(nil)
        return false
    }
}

struct RemoteWindowAccessor: NSViewRepresentable {
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
        window.setContentSize(NSSize(width: 980, height: 620))
        window.minSize = NSSize(width: 980, height: 620)
        window.maxSize = NSSize(width: 980, height: 620)
        window.styleMask.remove(.resizable)
        window.delegate = RemoteWindowDelegate.shared
        window.title = "HomeworkHelper Remote"
    }
}
