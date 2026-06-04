import Foundation

enum RemoteUITestFlags {
    static var showWindow: Bool {
        hasArgument("--ui-test-show-window") || hasEnvironment("HH_REMOTE_SHOW_WINDOW")
    }

    static var showSidebar: Bool {
        hasArgument("--ui-test-show-sidebar") || hasEnvironment("HH_REMOTE_SHOW_SIDEBAR")
    }

    static var showSummary: Bool {
        hasArgument("--ui-test-show-summary") || hasEnvironment("HH_REMOTE_SHOW_SUMMARY")
    }

    static var showPopover: Bool {
        hasArgument("--ui-test-show-popover") || hasEnvironment("HH_REMOTE_SHOW_POPOVER")
    }

    static var clickStatusItem: Bool {
        hasArgument("--ui-test-click-status-item") || hasEnvironment("HH_REMOTE_CLICK_STATUS_ITEM")
    }

    static var openSettings: Bool {
        hasArgument("--ui-test-open-settings") || hasEnvironment("HH_REMOTE_OPEN_SETTINGS")
    }

    static var skipExternalState: Bool {
        hasArgument("--ui-test-no-external-state")
            || hasEnvironment("HH_REMOTE_NO_EXTERNAL_STATE")
            || showWindow
            || showSidebar
            || showSummary
            || showPopover
            || clickStatusItem
            || openSettings
    }

    private static func hasArgument(_ argument: String) -> Bool {
        ProcessInfo.processInfo.arguments.contains(argument)
    }

    private static func hasEnvironment(_ key: String) -> Bool {
        ProcessInfo.processInfo.environment[key] == "1"
    }
}
