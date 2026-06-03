# Android Remote Client Rebuild Design

Last refreshed: 2026-06-03
Status: Active Android client implementation guide; existing Android full-parity code must not be resurrected

## 1. Decision

The Android client is rebuilt around the shared Remote Agent contract and should now be completed by tightening parity with the macOS client's data rules, not by restoring the removed legacy Android architecture.

Reason: the current Android product direction is game-first remote control. The Android app should mirror the macOS popover-first UX: the main screen is registered game status plus quick launch/stop, while pairing, power setup, diagnostics, Tailscale lifecycle automation, and device management are supporting setup tasks.

Keep:

- Gradle project, wrapper, package name `dev.homeworkhelper.remote`, manifest/resource scaffold.
- Kotlin + Jetpack Compose + Material 3 stack.
- Remote Agent API contract and Android Keystore requirement.
- Internal/device verification script entrypoints, updated to match rebuild phases.

Discard before rebuilding:

- Current `RemoteAppViewModel`, `RemoteRepository`, `RemoteApiClient`, `RemoteModels`, `RemoteScreens`, and platform integration code.
- Documents that claim Android full parity or device QA completion.
- Host-power execution assumptions such as `/remote/power/config` or `/remote/power/{action}` style flows.

## 2. Product goal

Build an Android-native remote play assistant for HomeworkHelper users.

Primary job:

> Open the app, immediately see the host's registered games and their state, then launch the desired host game with clear feedback.

Secondary jobs:

- Pair this Android device with the Remote Agent.
- Diagnose online/offline/auth state.
- View readiness and cached game state when the host is unavailable.
- Manage paired-device and token lifecycle tasks.
- Provide optional Android-local power control through Tailscale app binding, SmartThings Wake, and OpenSSH.
- Keep Android-only lifecycle automation explicit and reversible: app foreground may request Tailscale VPN ON, app background may request VPN OFF, but first login/VPN consent remains user-approved.
- Make HomeworkHelper HTTP/SSH calls feel like part of the Android client by allowing private builds to route those calls through an embedded tsnet node instead of requiring the user to operate both the client app and the external Tailscale app for ordinary app functions.

Non-goals for the first rebuild pass:

- Host-managed power side effects or `/remote/power/{action}` execution endpoints.
- Background sync, notifications, or WorkManager.
- Cloud relay or public Remote Agent exposure.
- Recreating macOS-specific Moonlight/AppKit/LoginItem settings.
- Moonlight/Apollo integration.

## 3. UX structure

The Android home screen is the equivalent of the macOS popover.

Recommended navigation:

1. **Home / Games**: default screen, game mirror, quick launch, pull-to-refresh, status feedback.
2. **Setup**: connection/pairing, power automation, paired devices, app behavior, diagnostics, fake smoke guidance.

Bottom navigation should contain only user-action surfaces. Information-only Power/More tabs are consolidated into Setup sections.

## 4. Home screen blueprint

Home header:

- App title and compact host status chip.
- Last sync time.
- Floating status message fixed just above bottom navigation.
- Pull-to-refresh gesture for snapshot refresh; no primary refresh button on Home.

Game list:

- Host-provided game icon when available; Material fallback when absent.
- Host resource icon URL beside progress when available.
- Game name, status text, progress meter/resource text.
- Today-played indicator and running-state emphasis.
- Primary `[실행]` button for `POST /remote/processes/{id}/launch`.
- Running games replace the launch action with a red `[중단]` button backed by `POST /remote/processes/{id}/stop` and a confirmation dialog.
- Disabled state with explicit reason when auth/offline/loading/in-flight.

Feedback states:

- Loading: preserve previous list; show refresh spinner/banner.
- Empty: explain that host has no registered games or pairing is needed.
- Offline: show cached games with stale marker.
- Auth rejected: preserve cache; show pairing/token recovery CTA.
- Launch/stop accepted: show success message and perform short command-chase refreshes so the card quickly mirrors host state.
- Launch failed: show failure without clearing game list.

Visual direction:

- Material 3 cards, large touch targets, strong status color semantics.
- Keep hierarchy simple: status banner -> game cards -> secondary setup entry.
- Avoid dense admin dashboards on the home screen.

## 5. Setup and support screen

Setup screen sections:

1. **연결/페어링**
2. **전원**
3. **기기**
4. **앱**

Setup screen responsibilities:

- Remote Agent URL.
- Device name.
- Pairing code.
- Pair/refresh token/clear local token actions.
- Server reachability and auth guidance.
- User-facing display preferences such as diagnostic section visibility.
- Power readiness explanation and OpenSSH/setup details.
- App-only `RemoteNetworkController` status for HomeworkHelper HTTP/SSH calls.
- Tailscale app binding status and host tailnet URL probing as an external fallback.
- Tailscale ON/OFF broadcast requests and optional foreground/background lifecycle automation as explicit fallback controls.
- Embedded tsnet auth URL display and `인증 열기` action when the app-only tailnet node needs interactive approval.
- SmartThings PAT input, PAT-only save path for already-known deviceId, `PC 켜기` device auto-selection, candidate selection, and manual deviceId fallback.
- Paired device list, device revoke, and revoked-device cleanup.
- Diagnostics and fake Remote Agent smoke guidance.

Power UI policy:

- Wake is enabled only after SmartThings PAT/OAuth authorization plus `PC 켜기` deviceId are present; deviceId is a target identifier and is never sufficient as SmartThings Cloud authorization.
- After pairing or online recovery, Android automatically creates/registers its SSH public key and runs marker-based SSH health.
- Sleep/restart/shutdown are enabled only after that automatic SSH registration/health chain succeeds.
- Restart/shutdown/sleep require a confirmation dialog; Wake may be one-tap.
- It must not call removed or host-managed power execution endpoints.

Tailscale UI policy:

- The first-class connection surface is the app-only RemoteNetworkController. It can use the Android system route or a private embedded tailnet bridge selected by build config.
- Embedded mode uses the checked-in Kotlin `TsnetEmbeddedTailnetBridge` wrapper plus an optional gomobile AAR. It should route Remote Agent HTTP and SSH sockets through tsnet while preserving the external Tailscale app controls as a manual/system fallback.
- If Tailscale is not installed, guide the user to install/open the official Android package.
- If Tailscale is installed, Android may request VPN connect/disconnect through the installed app and then re-inspect VPN state.
- The app must display that first-time Tailscale login, Android VPN consent, and account approval can require direct user confirmation in Tailscale.

## 6. Android implementation architecture

Use a small, rebuild-friendly architecture:

```text
app/src/main/java/dev/homeworkhelper/remote/
├── MainActivity.kt              # Activity + top-level Compose scaffold
├── data/RemoteApiClient.kt      # low-level HTTP/JSON client for shared /remote/* contract
├── data/RemoteModels.kt         # DTOs and mapping helpers
├── data/RemoteRepository.kt     # snapshot fetch and commands
├── data/SmartThingsClient.kt    # SmartThings REST list/command client
├── state/RemoteViewModel.kt     # UI state, refresh, pairing, launch and automation commands
├── platform/TokenStore.kt       # Android Keystore token store
├── platform/Preferences.kt      # non-secret settings
├── platform/AutomationPreferences.kt # SSH/SmartThings/Tailscale local settings
├── platform/AndroidSSHPowerManager.kt # SSHJ health and power commands
├── platform/RemoteNetworkController.kt # app-only network mode, HTTP/SSH transport hooks, embedded tailnet bridge boundary
├── platform/TsnetEmbeddedTailnetBridge.kt # reflection wrapper around optional gomobile tsnet AAR
├── platform/TailscaleBinding.kt # app detection, launch/install, VPN-state adapter
└── ui/                          # Home, Setup, shared components
```

The optional native bridge source lives outside the production Kotlin tree:

```text
native/tailnetbridge/
├── go.mod      # tailscale.com/tsnet + gomobile bind tool
├── bridge.go   # Configure/Start/EnsureConnectedJson/StatusJson/RequestJson/OpenTcp/Read/Write/CloseConn/Stop
└── bridge_test.go
```

`tools/build_android_tailnet_bridge.py` builds
`local-artifacts/android-tailnet/homeworkhelper-tailnet.aar` with
`gomobile bind -target=android/arm64 -androidapi=26
-javapkg=dev.homeworkhelper.remote.nativebridge`. The app includes that AAR
only when `homeworkhelper.android.embeddedTailnetAar` is set, so default system
route builds stay reproducible without Go/gomobile.

Rules:

- Keep low-level HTTP free of Compose state.
- Keep token persistence behind a small interface.
- Treat cached process snapshots as a first-class Home requirement.
- Do not introduce repository abstractions that only forward one method; keep layers small.
- Add background sync only after the foreground app is stable.

## 7. Shared Remote Agent API subset for Android v1

Required for Home:

- `GET /remote/status`
- `GET /remote/readiness`
- `GET /remote/processes`
- `POST /remote/processes/{id}/launch`
- `POST /remote/processes/{id}/stop`

Required for setup:

- `POST /remote/pair/confirm`
- `GET /remote/devices`
- `DELETE /remote/devices/{id}`
- `DELETE /remote/devices/revoked`

Required for automation setup:

- `GET /remote/power/status`
- `GET /remote/power/setup`
- `POST /remote/power/ssh-key`

Optional after Home is stable:

- `GET /remote/dashboard/summary`
- `GET /remote/beholder/incidents`
- `GET /remote/game-links`, `POST /remote/game-links`
- `GET /remote/mobile-sessions/active`, start/end mobile sessions
- `GET /remote/logging/config`, `PUT /remote/logging/config`

Do not use:

- `/remote/power/config`
- `/remote/power/{action}`
- `/remote/power/smartthings/devices`

Those belonged to older host-managed assumptions and are not valid Android execution contracts.

## 8. Assets and icons

Preferred assets:

- Host process icon URLs from `/remote/processes` (`icon_url`, `icon_urls`).
- Host resource icon URLs for progress/resource display (`resource_icon_url`, `resource_icon_urls`).
- Material Icons/Material 3 default visual language for fallback status symbols.

Do not add a custom icon pack for v1. The visual quality target should come from layout, spacing, status color, typography, and good empty/error states.

Icon caching:

- Use Coil memory/disk caching for Android v3 URL images.
- Add explicit app-level icon cache only if Coil behavior is insufficient after real-host testing.

## 9. Connectivity model

Android should share the supervisor concepts from `docs/remote/connection-supervisor-protocol.md`:

- `online`: Remote Agent and auth are OK.
- `offlineExpected`: host/network likely unavailable.
- `agentUnavailable`: network may exist but Remote Agent/HTTP is unavailable.
- `authRejected`: token rejected.
- transient loading/reconnecting states for UI feedback.

Android reachability and state mirroring:

- HTTP status probe first.
- Friendly messages for timeout, DNS, connection refused, 401/403.
- Preserve last successful game snapshot.
- Preserve the paired device token until explicit device revoke; Android should not rotate or locally delete it as part of ordinary setup.
- When paired and online, process state, running flags, and resource/progress metadata are host-authoritative and should overwrite local cached projection.
- When offline, Android may show cached games and locally projected progress using the `projection_*` metadata supplied by the host.
- Remote Agent HTTP and Android-local SSH should go through `RemoteNetworkController`; `homeworkhelper.android.remoteNetworkMode=system` preserves Android's system route, while `embedded` uses `TsnetEmbeddedTailnetBridge` by default and requires `homeworkhelper.android.embeddedTailnetAar` to bundle the native Go bridge.
- Embedded tsnet state is persistent and non-ephemeral under the app files directory. The first run may return `needs_auth` with an auth URL; Setup must expose that URL and an open-auth action.
- Tailscale app binding is Android-local only: request the installed Tailscale app to connect, poll local VPN state, and never mutate host-side Tailscale health.

## 10. Verification plan

Phase 0, rebuild scaffold:

```bash
./.venv/bin/python -m pytest tests/test_remote_android_client_static.py -q
./.venv/bin/python tools/build_android_tailnet_bridge.py
cd remote_clients/android/HomeworkHelperRemote && ./gradlew :app:assembleDebug --stacktrace
cd remote_clients/android/HomeworkHelperRemote && ./gradlew :app:assembleDebug -Phomeworkhelper.android.remoteNetworkMode=embedded -Phomeworkhelper.android.embeddedTailnetAar="$PWD/../../../local-artifacts/android-tailnet/homeworkhelper-tailnet.aar" --stacktrace
./.venv/bin/python tools/check_android_apk_artifact.py
```

Phase 1, Home and setup implementation:

- Static test for required v3 endpoints, icon payload fields, pull-to-refresh, launch/stop, device/token actions, Tailscale lifecycle markers, and no stale power endpoints.
- Unit/static checks for token store and process card labels.
- APK build.
- Fake Remote Agent serves PNG process/resource icons from `assets/` and smoke verifies image endpoint hits.
- Fake Remote Agent smoke should also exercise launch/stop command flow and the compact Setup section hierarchy.

Phase 2, physical device:

- Pairing and process-list sync on a real device.
- Cached game state survives app restart/offline host.
- Launch command accepted against a test Remote Agent.
- Tailscale foreground/background automation, SmartThings wake, OpenSSH power actions, and device revoke should be verified with explicit user-approved real-device scenarios.

## 11. Open questions for implementation phase

- Should Home include dashboard summary above or below game cards?
- Should Android v1 support Android-PC links immediately, or only after Home is stable?
- Which persistence API should replace SharedPreferences if settings grow: DataStore or simple SharedPreferences?
