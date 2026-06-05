import AppKit
import Carbon

final class RemoteGlobalShortcutRegistrar {
    static let shared = RemoteGlobalShortcutRegistrar()
    static let shortcutDescription = "⌘⌥G"
    static let disabledMessage = "전역 단축키가 비활성화되어 있습니다. 활성화하면 \(shortcutDescription)로 popover를 호출합니다."

    private static let hotKeySignature = fourCharCode("HHGR")
    private static let hotKeyID: UInt32 = 1

    private var hotKeyRef: EventHotKeyRef?
    private var eventHandlerRef: EventHandlerRef?

    private init() {}

    @discardableResult
    func setEnabled(_ enabled: Bool) -> String {
        if enabled {
            return register()
        }
        unregister()
        return Self.disabledMessage
    }

    @discardableResult
    func register() -> String {
        unregister()

        var eventType = EventTypeSpec(
            eventClass: OSType(kEventClassKeyboard),
            eventKind: UInt32(kEventHotKeyPressed)
        )
        let handlerStatus = InstallEventHandler(
            GetApplicationEventTarget(),
            { _, event, _ in
                guard let event else { return OSStatus(eventNotHandledErr) }
                var hotKeyID = EventHotKeyID()
                let status = GetEventParameter(
                    event,
                    EventParamName(kEventParamDirectObject),
                    EventParamType(typeEventHotKeyID),
                    nil,
                    MemoryLayout<EventHotKeyID>.size,
                    nil,
                    &hotKeyID
                )
                guard status == noErr,
                      hotKeyID.signature == RemoteGlobalShortcutRegistrar.hotKeySignature,
                      hotKeyID.id == RemoteGlobalShortcutRegistrar.hotKeyID else {
                    return OSStatus(eventNotHandledErr)
                }
                DispatchQueue.main.async {
                    NotificationCenter.default.post(
                        name: Notification.Name("HomeworkHelperRemoteGlobalShortcutPressed"),
                        object: nil
                    )
                }
                return noErr
            },
            1,
            &eventType,
            nil,
            &eventHandlerRef
        )
        guard handlerStatus == noErr else {
            unregister()
            return "전역 단축키 핸들러 등록 실패: OSStatus \(handlerStatus)"
        }

        let hotKeyID = EventHotKeyID(signature: Self.hotKeySignature, id: Self.hotKeyID)
        let modifiers = UInt32(cmdKey | optionKey)
        let registerStatus = RegisterEventHotKey(
            UInt32(kVK_ANSI_G),
            modifiers,
            hotKeyID,
            GetApplicationEventTarget(),
            0,
            &hotKeyRef
        )
        guard registerStatus == noErr else {
            unregister()
            return "\(Self.shortcutDescription) 등록 실패: 이미 다른 앱이나 시스템 단축키가 사용 중일 수 있습니다. OSStatus \(registerStatus)"
        }
        return "\(Self.shortcutDescription)로 메뉴바 popover를 호출합니다."
    }

    func unregister() {
        if let hotKeyRef {
            UnregisterEventHotKey(hotKeyRef)
            self.hotKeyRef = nil
        }
        if let eventHandlerRef {
            RemoveEventHandler(eventHandlerRef)
            self.eventHandlerRef = nil
        }
    }

    private static func fourCharCode(_ value: String) -> OSType {
        value.utf8.reduce(0) { result, byte in
            (result << 8) + OSType(byte)
        }
    }
}
