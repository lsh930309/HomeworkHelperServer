# macOS 26+ Full-Native Liquid Glass 전환 계획서

작성일: 2026-05-15  
대상: `remote_clients/macos/HomeworkHelperRemote`  
목표 브랜치 기준: 현재 macOS 클라이언트는 SwiftUI + AppKit 보조 코드(`NSStatusItem`, `NSPopover`, `NSWindowDelegate`, `NSVisualEffectView`) 기반이며, 이번 문서는 **중간 호환 단계 없이 macOS 26 이상 전용 full-native Liquid Glass UI로 한 번에 교체**하기 위한 실행 계획이다.

---

## 1. 목표와 비목표

### 목표

1. macOS 클라이언트의 UI 표면을 macOS 26+ 공식 Liquid Glass API로 전환한다.
2. 기존 `NSVisualEffectView` 기반 유사 glass 배경과 `.thinMaterial` 기반 카드/필을 제거한다.
3. SwiftUI 표면은 `glassEffect(_:in:)`, `Glass`, `GlassEffectContainer`, `glassEffectID(_:in:)`, `GlassEffectTransition`, `GlassButtonStyle`/glass button style 계열을 우선 사용한다.
4. AppKit이 필요한 창/팝오버 레벨에서는 `NSGlassEffectView`와 `NSGlassEffectContainerView`를 사용한다.
5. 다음 기존 기능은 회귀 없이 보존한다.
   - 메인 창은 항상 1개만 존재한다.
   - Spotlight/Dock 재포커스 시 새 창이 추가 생성되지 않는다.
   - 메뉴바 popover 토글, Dock reopen, ESC 창 숨김 동작이 유지된다.
   - Cmd+R 새로고침, Cmd+, 설정, 메뉴바 > 원격 > 설정 동작이 유지된다.
   - 페어링 토큰/Keychain/자동 복구 흐름은 변경하지 않는다.
   - 아이콘 고품질 캐시/표시 경로는 변경하지 않는다.
   - 설정 탭/플레이 요약 토글/비 HoYoLab 진행률 표시 토글은 유지한다.

### 비목표

1. macOS 25 이하 호환 fallback은 구현하지 않는다.
2. 호스트 API/Windows 호스트 앱은 수정하지 않는다. 이 작업은 클라이언트 GUI API 전환이다.
3. SSE/WebSocket 등 상태 동기화 구조는 바꾸지 않는다.
4. 아이콘 추출/캐시 정책은 바꾸지 않는다.
5. 새 외부 dependency는 추가하지 않는다.

---

## 2. 공식 API 근거

Apple 공식 문서 기준으로 macOS 26 Liquid Glass 전환에 사용할 API는 다음이다.

- Apple “What’s new in macOS 26”: macOS 26의 새 디자인은 Liquid Glass를 핵심 디자인 시스템으로 소개한다.  
  https://developer.apple.com/macos/whats-new/
- SwiftUI `View.glassEffect(_:in:)`: SwiftUI view에 Liquid Glass 효과를 적용한다.  
  https://developer.apple.com/documentation/swiftui/view/glasseffect%28_%3Ain%3A%29
- SwiftUI `Glass`: Liquid Glass material 설정 구조체. `interactive(_:)`, `tint(_:)`, `.regular`, `.clear`, `.identity` 등을 사용한다.  
  https://developer.apple.com/documentation/swiftui/glass
- SwiftUI “Applying Liquid Glass to custom views”: custom view에는 `glassEffect`를 적용하고, 여러 glass shape는 `GlassEffectContainer`로 결합하는 것이 권장된다.  
  https://developer.apple.com/documentation/SwiftUI/Applying-Liquid-Glass-to-custom-views
- SwiftUI updates: `glassEffect`, glass button style, `ToolbarSpacer`, `scrollEdgeEffectStyle`, `backgroundExtensionEffect`가 Liquid Glass 관련 SwiftUI 업데이트에 포함된다.  
  https://developer.apple.com/documentation/updates/swiftui
- AppKit `NSGlassEffectView`: AppKit view content를 dynamic glass effect 안에 넣는 공식 Liquid Glass view.  
  https://developer.apple.com/documentation/appkit/nsglasseffectview
- AppKit `NSGlassEffectContainerView`: 여러 descendant glass effect view를 효율적으로 병합하기 위한 AppKit container.  
  https://developer.apple.com/documentation/appkit/nsglasseffectcontainerview

---

## 3. 현재 코드 기준 영향 범위

### 핵심 파일

- `remote_clients/macos/HomeworkHelperRemote/Package.swift`
- `remote_clients/macos/HomeworkHelperRemote/Sources/HomeworkHelperRemote/HomeworkHelperRemoteApp.swift`
- `remote_clients/macos/HomeworkHelperRemote/Sources/HomeworkHelperRemote/RemoteWindowAccessor.swift`
- `tests/test_remote_macos_client_static.py`

### 현재 제거/교체 대상

1. `RemoteWindowAccessor.swift`
   - `RemoteGlassBackground: NSViewRepresentable`
   - 내부 `NSVisualEffectView`
   - `view.material = .hudWindow`
   - `view.blendingMode = .behindWindow`
2. `HomeworkHelperRemoteApp.swift`
   - `RemoteGlassBackground().ignoresSafeArea()`
   - `.background(.thinMaterial, in: RoundedRectangle(...))`
   - `.background(.thinMaterial, in: Capsule())`
   - 일반 `GroupBox`를 그대로 쓰는 주요 패널들
   - 일반 `.buttonStyle(.bordered)` 또는 `.buttonStyle(.borderless)` 중 glass button으로 바꿔야 할 주요 action 버튼
3. 테스트
   - 현재는 `NSVisualEffectView`, `.thinMaterial` 존재를 기대하는 정적 테스트가 있다면 제거/반전해야 한다.
   - 신규 Liquid Glass API 존재와 legacy material 제거를 계약으로 고정한다.

---

## 4. 전환 원칙

1. **macOS 26 이상 전용**
   - `Package.swift` deployment target을 macOS 26.0 이상으로 올린다.
   - Xcode 26 / macOS 26 SDK가 전제다.
   - macOS 25 이하 fallback과 `#available` runtime fallback은 만들지 않는다.

2. **SwiftUI 우선, AppKit은 창/호스트 레벨만**
   - 카드, 섹션, pill, 버튼, popover content, settings content는 SwiftUI `glassEffect` 중심으로 전환한다.
   - 실제 `NSWindow` 설정, popover hosting, window sizing, single-window 제어는 기존 AppKit 보조 구조를 유지한다.
   - 전체 창 배경 또는 AppKit host layer가 필요할 때만 `NSGlassEffectView`/`NSGlassEffectContainerView` wrapper를 둔다.

3. **Liquid Glass는 남발하지 않고 계층화한다**
   - 루트: `GlassEffectContainer`
   - 주요 surface: dashboard main panel, sidebar panel, game card, popover, settings section
   - 소형 surface: host status pill, power quick buttons, refresh/settings buttons
   - 텍스트/아이콘 자체에는 glass를 직접 적용하지 않는다.

4. **컴팩트함 유지**
   - 현재 UX 철학인 “직관적, 단순함, 컴팩트함”을 유지한다.
   - Liquid Glass 적용 때문에 padding/spacing이 커지면 안 된다.
   - 기존 window size 계산(`RemoteWindowLayout`)은 유지하되 glass 외곽 stroke/halo가 잘리지 않도록 필요한 최소 여백만 조정한다.

5. **기능 회귀 방지 우선순위**
   - UI 외관보다 먼저 single-window, settings command, popover pairing status, token persistence, refresh command가 유지되는지 테스트한다.
   - glass refactor 중 view model과 API client는 건드리지 않는다.

---

## 5. 작업 전 준비 조건

1. 로컬 도구
   - macOS 26 이상
   - Xcode 26 이상 또는 macOS 26 SDK 포함 Command Line Tools
   - `swift --version`과 `xcrun --show-sdk-version`으로 SDK 확인

2. 기준 검증
   - 작업 시작 전 현재 브랜치에서 다음이 통과해야 한다.
     ```bash
     ./.venv/bin/python -m pytest -q
     swift build --package-path remote_clients/macos/HomeworkHelperRemote
     ```

3. 기준 스크린샷
   - 루트의 최신 `image copy *.png` 중 검수 기준이 되는 메인 GUI와 popover 이미지를 보관한다.
   - 신규 Liquid Glass 적용 후 같은 화면을 다시 찍어 비교한다.

---

## 6. 상세 구현 계획

## 6.1 Package / deployment target 업데이트

파일: `remote_clients/macos/HomeworkHelperRemote/Package.swift`

변경:

```swift
platforms: [.macOS("26.0")]
```

주의:
- Xcode 26 PackageDescription에서 `.macOS(.v26)`가 지원되면 그 형태도 가능하지만, toolchain 호환성을 위해 문자열 지정(`"26.0"`)을 우선 검토한다.
- 이 작업 후 구버전 SwiftPM으로는 빌드가 실패하는 것이 정상이다.

테스트 계약:
- `Package.swift`에 `.macOS("26.0")` 또는 `.macOS(.v26)`가 있어야 한다.
- `.macOS(.v13)`은 제거되어야 한다.

---

## 6.2 Liquid Glass theme/helper 파일 추가

신규 파일 권장:  
`remote_clients/macos/HomeworkHelperRemote/Sources/HomeworkHelperRemote/RemoteLiquidGlass.swift`

목적:
- Liquid Glass 적용을 한 파일에 모아 UI 전체의 radius/tint/interactive 정책을 일관화한다.
- 추후 실제 API 시그니처 차이가 있으면 이 파일 중심으로 수정한다.

권장 구성:

```swift
import SwiftUI
import AppKit

enum RemoteGlassMetrics {
    static let windowCornerRadius: CGFloat = 24
    static let sectionCornerRadius: CGFloat = 18
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
        let shape = RoundedRectangle(cornerRadius: radius, style: .continuous)
        content
            .glassEffect(glass, in: shape)
    }

    private var radius: CGFloat {
        switch role {
        case .window: return RemoteGlassMetrics.windowCornerRadius
        case .section, .settings, .popover: return RemoteGlassMetrics.sectionCornerRadius
        case .card: return RemoteGlassMetrics.cardCornerRadius
        case .button: return RemoteGlassMetrics.buttonCornerRadius
        case .pill: return RemoteGlassMetrics.pillCornerRadius
        }
    }

    private var glass: Glass {
        var value = Glass.regular
        if let tint { value = value.tint(tint) }
        value = value.interactive(interactive)
        return value
    }
}

extension View {
    func remoteGlass(_ role: RemoteGlassRole, interactive: Bool = false, tint: Color? = nil) -> some View {
        modifier(RemoteGlassSurface(role: role, interactive: interactive, tint: tint))
    }
}
```

실제 Xcode 26 SDK에서 `Glass.regular` / `.tint` / `.interactive` chaining 문법 차이가 있으면 공식 시그니처에 맞춰 조정한다.

테스트 계약:
- `RemoteLiquidGlass.swift` 존재
- `glassEffect` 사용
- `GlassEffectContainer` 사용 위치 존재
- `NSVisualEffectView` 미사용

---

## 6.3 AppKit Liquid Glass bridge 추가

신규 또는 기존 파일:  
`RemoteLiquidGlass.swift` 또는 `RemoteWindowAccessor.swift`

목적:
- `NSVisualEffectView`를 제거하고, 창/팝오버 host 레벨에서 필요할 경우 `NSGlassEffectView` / `NSGlassEffectContainerView`를 사용한다.

권장 구현:

```swift
struct RemoteAppKitGlassHost<Content: View>: NSViewRepresentable {
    let cornerRadius: CGFloat
    let content: Content

    init(cornerRadius: CGFloat = RemoteGlassMetrics.windowCornerRadius, @ViewBuilder content: () -> Content) {
        self.cornerRadius = cornerRadius
        self.content = content()
    }

    func makeNSView(context: Context) -> NSGlassEffectContainerView {
        let container = NSGlassEffectContainerView()
        let glass = NSGlassEffectView()
        glass.cornerRadius = cornerRadius
        glass.contentView = NSHostingView(rootView: content)
        container.addSubview(glass)
        glass.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([
            glass.leadingAnchor.constraint(equalTo: container.leadingAnchor),
            glass.trailingAnchor.constraint(equalTo: container.trailingAnchor),
            glass.topAnchor.constraint(equalTo: container.topAnchor),
            glass.bottomAnchor.constraint(equalTo: container.bottomAnchor)
        ])
        return container
    }

    func updateNSView(_ container: NSGlassEffectContainerView, context: Context) {
        guard let glass = container.subviews.compactMap({ $0 as? NSGlassEffectView }).first,
              let hosting = glass.contentView as? NSHostingView<Content> else { return }
        glass.cornerRadius = cornerRadius
        hosting.rootView = content
    }
}
```

주의:
- 이 bridge는 “fallback”이 아니라 AppKit 공식 Liquid Glass API 사용이다.
- SwiftUI `glassEffect`만으로 충분하면 root host bridge는 생략 가능하지만, `NSVisualEffectView` 제거 후 창 전체 배경의 glass depth가 약하면 이 bridge를 적용한다.
- `NSGlassEffectView.Style`의 실제 case는 Xcode 26 문서/자동완성 기준으로 확인 후 지정한다. 지정하지 않아도 기본 style이 의도와 맞으면 기본값 유지가 더 안전하다.

---

## 6.4 창 배경 전환

파일: `RemoteWindowAccessor.swift`, `HomeworkHelperRemoteApp.swift`

현재:
- `RemoteGlassBackground`가 `NSVisualEffectView`를 생성한다.
- `RemoteDashboardView` root `ZStack` 최하단에 `RemoteGlassBackground().ignoresSafeArea()`가 있다.

변경:
1. `RemoteGlassBackground` 삭제 또는 `RemoteAppKitGlassHost` 기반으로 교체한다.
2. `RemoteDashboardView` root를 `GlassEffectContainer`로 감싼다.
3. 전체 창 content는 transparent window 위에 Liquid Glass section/card들이 떠 있는 구조로 만든다.

권장 구조:

```swift
var body: some View {
    GlassEffectContainer {
        HStack(spacing: 0) {
            ...
        }
        .padding(10) // glass edge가 잘리지 않는 최소 padding만
    }
    .frame(width: targetSize.width, height: targetSize.height)
    .background(RemoteWindowAccessor(...))
    ...
}
```

`RemoteWindowAccessor.configure(window:)` 유지 사항:
- `window.isOpaque = false`
- `window.backgroundColor = .clear`
- `window.titlebarAppearsTransparent = true`
- `RemoteAppDelegate.prepareMainWindow(window)`
- single-window dedupe 로직 유지

삭제/금지:
- `NSVisualEffectView`
- `.hudWindow`
- `RemoteGlassBackground`가 legacy visual effect를 쓰는 형태

---

## 6.5 Dashboard main layout 전환

파일: `HomeworkHelperRemoteApp.swift`

대상:
- `RemoteDashboardView`
- `HeaderStatusView`
- `GameSectionView`
- `RemoteGameCard`
- `PlaySummaryView`
- `BeholderIncidentSummaryView`

변경 방향:

1. `GroupBox` 기반 섹션을 `RemoteGlassSection`으로 대체한다.

권장 신규 component:

```swift
struct RemoteGlassSection<Label: View, Content: View>: View {
    @ViewBuilder let label: Label
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            label
                .font(.headline)
            content
        }
        .padding(12)
        .remoteGlass(.section)
    }
}
```

2. `GameSectionView`
   - `GroupBox` 제거
   - header row + horizontal cards를 `RemoteGlassSection`으로 구성
   - refresh button은 glass button style 또는 `.remoteGlass(.button, interactive: true)` 적용

3. `RemoteGameCard`
   - `.background(.thinMaterial, in: RoundedRectangle(...))` 제거
   - `.remoteGlass(.card, interactive: true)` 적용
   - running 상태 border는 유지하되 Liquid Glass와 충돌하지 않게 opacity 낮춤
   - launch button은 glass button style 적용

4. `PlaySummaryView`, `BeholderIncidentSummaryView`
   - `GroupBox` 제거
   - `RemoteGlassSection` 사용
   - 기존 compact height 계산은 유지

5. `HeaderStatusView`
   - 작은 설명문은 이미 제거되어 있으므로 재도입하지 않는다.
   - host status pill은 tinted glass pill로 전환한다.

---

## 6.6 Sidebar 전환

파일: `HomeworkHelperRemoteApp.swift`

대상:
- `RemoteSidebarView`
- `SettingsOpenButton`
- `PowerSquareButton`
- `SidebarInfoRow`

변경 방향:
1. sidebar 전체를 `.remoteGlass(.section)` 또는 AppKit/SwiftUI glass panel로 감싼다.
2. 내부 `GroupBox("연결")`, `GroupBox("PC 전원")`, `GroupBox("앱")`를 `RemoteGlassSection`으로 대체한다.
3. `SettingsOpenButton`은 `SettingsLink` 유지 + glass button style 적용.
4. 기존 padding 회귀 방지:
   - sidebar root `.padding(.horizontal, 18)` 유지 또는 glass edge 포함해 `16~18` 유지
   - `[설정 열기]` 버튼이 좌측 끝에 붙지 않는 테스트 유지
5. sidebar 기본 숨김 및 재표시 시 숨김 상태 유지 로직은 변경하지 않는다.

---

## 6.7 Menu bar popover 전환

파일: `HomeworkHelperRemoteApp.swift`

대상:
- `MenuBarPopoverView`
- `MenuBarGameRow`
- `HostStatusPill`
- popover 생성부 `configureStatusItem()`

변경 방향:
1. `MenuBarPopoverView.body` root를 `GlassEffectContainer`로 감싼다.
2. 전체 popover content에 `.remoteGlass(.popover)`를 적용한다.
3. 하단 3개 버튼과 전원 버튼 row는 spacing `8` 유지.
4. 버튼은 glass style로 통일한다.
5. `MenuBarGameRow`의 row 자체에는 강한 glass를 매번 주지 않는다. popover 전체 glass 위에 row는 plain content로 두되 hover/interactive가 필요하면 약한 `.clear` glass를 검토한다.
6. pairing status pill은 tinted glass pill로 전환하되 view model 상태 반영 로직은 절대 변경하지 않는다.

테스트 계약:
- `MenuBarPopoverView` 안에 `GlassEffectContainer` 또는 `.remoteGlass(.popover)` 존재
- 하단 `HStack(spacing: 8)` 유지
- `HostStatusPill` 유지
- `popover.performClose(nil)` 유지

---

## 6.8 Settings window 전환

파일: `HomeworkHelperRemoteApp.swift`

대상:
- `RemoteSettingsView`
- `SettingsTabScrollView`
- 각 `settings*Tab`

변경 방향:
1. Settings root를 `GlassEffectContainer`로 감싼다.
2. `TabView`는 유지하되, 각 tab content 내부 섹션을 `RemoteGlassSection`으로 교체한다.
3. 설정 항목이 많으므로 현재 탭 구분은 유지한다.
4. 각 탭의 top-level scroll content에는 배경 material을 넣지 말고 section 단위 glass만 적용한다.
5. `SettingsLink`, Cmd+, menu bar 설정 진입 로직은 변경하지 않는다.

주의:
- Settings window는 SwiftUI `Settings` scene이 관리하므로 단일 메인 창 dedupe 대상이 아니다.
- `RemoteAppDelegate.mainWindowIdentifier`와 settings window가 섞이지 않게 `RemoteWindowAccessor`는 dashboard에만 붙인다.

---

## 6.9 Button style 전환

대상:
- refresh
- launch
- power square buttons
- settings open
- popover 하단 3개 버튼
- settings action buttons 중 자주 쓰는 버튼

전환 원칙:
1. macOS 26 SDK가 제공하는 glass button style을 우선 사용한다.
   - 공식 SwiftUI updates는 `buttonStyle(_:)`로 glass를 적용할 수 있음을 언급한다.
   - 실제 문법은 Xcode 26 자동완성 기준으로 다음 중 확인한다.
     - `.buttonStyle(.glass)`
     - `.buttonStyle(GlassButtonStyle())`
     - `.buttonStyle(GlassProminentButtonStyle())`
2. destructive button은 role 표시를 유지한다.
3. icon-only refresh는 icon-only 유지.
4. 버튼 크기는 기존 `.controlSize(.small)` / `.mini` 계약을 최대한 유지한다.

테스트 계약:
- 주요 action button에 glass button style marker 존재
- refresh icon-only 유지
- `Button(role: .destructive)` 유지

---

## 6.10 Scroll / edge treatment

대상:
- dashboard main `ScrollView`
- settings `SettingsTabScrollView`
- game horizontal scroll

전환 방향:
1. `scrollEdgeEffectStyle(_:for:)`를 사용할 수 있으면 settings/dashboard vertical scroll에 적용한다.
2. game horizontal scroll은 현재 custom AppKit drag scroll이므로 일단 유지한다.
3. `backgroundExtensionEffect()`는 창 safe area 외곽 mirroring이 실제로 필요한 경우에만 적용한다. 현재 compact desktop utility app에서는 과하면 지저분할 수 있으므로 기본 계획에서는 보류한다.

---

## 7. 회귀 방지 체크리스트

### 창/앱 동작

- [ ] Spotlight로 앱 focus 전환을 반복해도 메인 창은 1개만 존재한다.
- [ ] Dock icon 클릭 시 popover가 아니라 메인 창만 focus/복원된다.
- [ ] 메뉴바 icon 클릭은 popover toggle만 수행한다.
- [ ] ESC는 메인 창을 숨긴다.
- [ ] 창 숨김 후 재표시해도 sidebar는 숨김 상태로 시작한다.
- [ ] Cmd+R은 refresh를 실행한다.
- [ ] Cmd+,는 settings를 연다.
- [ ] 메뉴바 > 원격 > 설정은 settings를 연다.

### 페어링/상태

- [ ] 기존 Keychain token이 유지된다.
- [ ] 앱 재실행 후 자동 연결/페어링 상태가 유지된다.
- [ ] pairing 완료 후 popover status pill이 즉시 갱신된다.
- [ ] host offline/paired/syncing 상태 표시가 유지된다.

### UI/레이아웃

- [ ] `NSVisualEffectView` 흔적이 없다.
- [ ] `.thinMaterial` 배경이 남아 있지 않다.
- [ ] dashboard, sidebar, game card, popover, settings sections가 Liquid Glass로 보인다.
- [ ] game icon smoothing/quality가 유지된다.
- [ ] sidebar `[설정 열기]` 버튼 좌측 padding이 유지된다.
- [ ] play summary off 상태에서 창 하단 공백이 다시 생기지 않는다.
- [ ] 비 HoYoLab 진행률 표시 토글과 자연어 시간 표시가 유지된다.

---

## 8. 테스트 계획

### 8.1 정적 테스트 업데이트

파일: `tests/test_remote_macos_client_static.py`

추가/수정할 assertion:

```python
package = _read(Path("remote_clients/macos/HomeworkHelperRemote/Package.swift"))
assert '.macOS("26.0")' in package or '.macOS(.v26)' in package
assert '.macOS(.v13)' not in package

app = _read(SOURCE_ROOT / "HomeworkHelperRemoteApp.swift")
window_accessor = _read(SOURCE_ROOT / "RemoteWindowAccessor.swift")
liquid = _read(SOURCE_ROOT / "RemoteLiquidGlass.swift")

assert "glassEffect" in app or "glassEffect" in liquid
assert "GlassEffectContainer" in app or "GlassEffectContainer" in liquid
assert "NSGlassEffectView" in liquid or "NSGlassEffectView" in window_accessor
assert "NSGlassEffectContainerView" in liquid or "NSGlassEffectContainerView" in window_accessor
assert "NSVisualEffectView" not in window_accessor
assert "NSVisualEffectView" not in liquid
assert ".thinMaterial" not in app
assert "RemoteGlassBackground" not in app

# 단일 창 회귀 방지
assert "Window(RemoteAppDelegate.mainWindowTitle, id: RemoteAppDelegate.mainWindowIdentifier)" in app
assert "WindowGroup(" not in app
assert "deduplicateMainWindows" in app
assert "RemoteAppDelegate.prepareMainWindow(window)" in window_accessor
assert ".close()" not in app

# 명령/설정 회귀 방지
assert "SettingsLink" in app
assert 'Selector(("showSettingsWindow:"))' in app
assert '.keyboardShortcut(",", modifiers: .command)' in app
assert '.keyboardShortcut("r", modifiers: .command)' in app
assert ".onExitCommand" in app

# 기존 기능 marker 유지
assert "showPlaySummary" in _read(SOURCE_ROOT / "RemoteDashboardViewModel.swift")
assert "cycleProgressDisplayMode" in _read(SOURCE_ROOT / "RemoteDashboardViewModel.swift")
assert "displayIconImage" in _read(SOURCE_ROOT / "RemoteDashboardViewModel.swift")
```

### 8.2 빌드 검증

Xcode 26/macOS 26 SDK 환경에서:

```bash
swift build --package-path remote_clients/macos/HomeworkHelperRemote
```

현재 CI/로컬이 Xcode 26이 아니면 이 단계는 실패한다. 이 실패는 환경 문제로 기록하고, Xcode 26 환경에서 재검증한다.

### 8.3 Python test suite

```bash
./.venv/bin/python -m pytest -q
```

주의:
- 일부 remote logging 테스트는 사용자 config backup 디렉터리에 쓰기를 수행할 수 있으므로 sandbox 밖 실행이 필요할 수 있다.

### 8.4 수동 검수

1. 앱 실행
2. 메인 GUI 스크린샷 저장
3. 메뉴바 popover 스크린샷 저장
4. Spotlight로 앱 focus 전환 5회 반복
5. 창 개수 확인: 항상 1개
6. Cmd+, settings 열림 확인
7. 메뉴바 > 원격 > 설정 열림 확인
8. Cmd+R refresh 확인
9. ESC 창 숨김 확인
10. play summary off/on window compact resize 확인
11. host/client 재실행 후 pairing 유지 확인

---

## 9. 예상 구현 순서

1. `Package.swift` macOS 26 target 전환
2. `RemoteLiquidGlass.swift` 추가
3. `RemoteWindowAccessor.swift`에서 `NSVisualEffectView` 제거
4. dashboard root에 `GlassEffectContainer` 적용
5. `RemoteGlassSection` 도입
6. `GameSectionView`, `RemoteGameCard` 전환
7. `RemoteSidebarView`, `SettingsOpenButton`, `PowerSquareButton` 전환
8. `MenuBarPopoverView`, `HostStatusPill` 전환
9. `RemoteSettingsView`와 settings tab sections 전환
10. button styles glass 전환
11. 정적 테스트 업데이트
12. Swift build
13. full pytest
14. 수동 스크린샷/Spotlight 검수
15. Korean Lore 커밋/푸시

---

## 10. 구현 시 주의할 구체적 위험

### 위험 1: Xcode 26 API 시그니처 차이

공식 문서에는 `glassEffect(_:in:)`, `Glass`, `NSGlassEffectView` 등이 확인되지만, 실제 beta/GM SDK에서 style case나 button style shorthand가 다를 수 있다.

대응:
- API 호출은 `RemoteLiquidGlass.swift`에 집중시킨다.
- compile error가 나면 이 파일만 수정해 전체 UI에 반영되게 한다.

### 위험 2: GlassEffectContainer 중첩 과다

과도한 glass container 중첩은 성능 저하와 어색한 refraction을 만들 수 있다.

대응:
- root 1개 + 주요 section/card 단위만 적용한다.
- row마다 glass를 주지 않는다.
- popover는 popover root 위주로 적용한다.

### 위험 3: compact layout 깨짐

Liquid Glass edge/halo 때문에 padding을 늘리고 싶어질 수 있지만, 이 앱의 핵심 철학은 compact함이다.

대응:
- section/card 내부 padding은 기존 값에서 `+0~2` 범위만 허용한다.
- window size 계산 변경은 필요한 최소만 한다.

### 위험 4: 단일 창 제어 회귀

SwiftUI scene 변경이나 settings scene 수정 중 Window/Settings 분리가 깨질 수 있다.

대응:
- `Window(RemoteAppDelegate.mainWindowTitle, id: RemoteAppDelegate.mainWindowIdentifier)` 유지
- `RemoteWindowAccessor`는 dashboard에만 유지
- `Settings` scene에는 `RemoteWindowAccessor`를 붙이지 않는다.
- `deduplicateMainWindows` 테스트 유지

### 위험 5: Settings command 회귀

이전 검수에서 Cmd+,와 메뉴바 설정 진입이 깨졌던 이력이 있다.

대응:
- `SettingsLink`와 fallback `RemoteAppDelegate.openSettingsWindow()` 둘 다 유지한다.
- command menu 안에서 `SettingsLink`가 fallback보다 먼저 존재하는 정적 테스트 유지.

---

## 11. 완료 기준

이 작업은 아래 조건을 모두 만족해야 완료로 본다.

1. `NSVisualEffectView`가 macOS 클라이언트 코드에서 제거되어 있다.
2. `.thinMaterial` 기반 glass 흉내 배경이 제거되어 있다.
3. SwiftUI `glassEffect`와 `GlassEffectContainer`가 dashboard/popover/settings의 실제 UI에 적용되어 있다.
4. 필요 시 AppKit `NSGlassEffectView`/`NSGlassEffectContainerView`가 window host layer에 적용되어 있다.
5. `Package.swift`가 macOS 26 이상 전용으로 변경되어 있다.
6. `swift build --package-path remote_clients/macos/HomeworkHelperRemote`가 Xcode 26/macOS 26 SDK에서 통과한다.
7. `./.venv/bin/python -m pytest -q`가 통과한다.
8. Spotlight 반복 focus 전환 후 메인 창이 1개만 유지된다.
9. Cmd+, / 메뉴바 설정 / sidebar 설정 버튼이 모두 settings를 연다.
10. 앱 재실행 후 pairing/token 상태가 유지된다.
11. 메인 GUI와 popover 스크린샷에서 Liquid Glass가 기존 `NSVisualEffectView`보다 명확히 native하게 보인다.

---

## 12. 추천 Korean Lore 커밋 메시지 초안

```text
macOS 26 Liquid Glass로 UI 기반을 단일화하기 위해

macOS 25 이하 fallback을 제거하고 SwiftUI/AppKit 공식 Liquid Glass API로 dashboard, popover, settings surface를 전환한다. 기존 창 제어, 페어링, 아이콘 캐시, 단축키 동작은 유지한다.

Constraint: 사용 환경을 macOS 26 이상과 Xcode 26 SDK로 고정함
Rejected: NSVisualEffectView 기반 유사 glass 유지 | 공식 Liquid Glass와 시각/동작 차이가 커서 전면 교체가 목적에 맞음
Rejected: macOS 25 이하 fallback 병행 | 분기와 테스트 비용이 커지고 이번 목표가 최신 환경 전용임
Confidence: medium
Scope-risk: broad
Directive: view model/API/token/cache 로직은 UI glass 전환 중 수정하지 말 것
Tested: ./.venv/bin/python -m pytest -q; swift build --package-path remote_clients/macos/HomeworkHelperRemote; Spotlight 반복 focus 수동 검수; Cmd+, 설정 수동 검수
Not-tested: macOS 25 이하 실행
Co-authored-by: OmX <omx@oh-my-codex.dev>
```

---

## 13. 기반 기능 회귀 테스트 체크리스트

Liquid Glass 전환 작업자는 별도 루트 문서 `macos-client-regression-checklist.md`의 모든 항목을 실행하고, 각 항목마다 `테스트 방법`, `테스트 결과`, `통과 판정 근거`를 채워야 한다. 체크박스만 표시하거나 자동 테스트 명령만 적는 것은 완료로 인정하지 않는다.
