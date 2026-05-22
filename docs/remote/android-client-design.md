# Android Remote Client Rebuild Design

Last refreshed: 2026-05-19
Status: Active v3 implementation design; existing Android full-parity code must not be resurrected

## 1. Decision

The Android client will be rebuilt from a clean scaffold.

Reason: the current Android code and documents describe a full-parity client, but the product direction has changed. The Android app should now mirror the macOS popover-first UX: the main screen is registered game status and quick launch. Pairing, power setup, diagnostics, Usage Access, and device management are supporting setup tasks, not the main experience.

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
- Manage optional Android-PC mobile-session features.
- Provide optional Android-local power control through Tailscale app binding, SmartThings Wake, and OpenSSH.

Non-goals for the first rebuild pass:

- Host-managed power side effects or `/remote/power/{action}` execution endpoints.
- Background sync, notifications, or WorkManager.
- Cloud relay or public Remote Agent exposure.
- Recreating every macOS settings option.
- Moonlight/Apollo integration.

## 3. UX structure

The Android home screen is the equivalent of the macOS popover.

Recommended navigation:

1. **Home / Games**: default screen, game mirror, quick launch, pull-to-refresh, status feedback.
2. **Setup**: pairing, Remote Agent URL, auth recovery, display preferences, power readiness, diagnostics, fake smoke guidance.

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
- Disabled state with explicit reason when auth/offline/loading/running.

Feedback states:

- Loading: preserve previous list; show refresh spinner/banner.
- Empty: explain that host has no registered games or pairing is needed.
- Offline: show cached games with stale marker.
- Auth rejected: preserve cache; show pairing/token recovery CTA.
- Launch accepted: show success message and refresh.
- Launch failed: show failure without clearing game list.

Visual direction:

- Material 3 cards, large touch targets, strong status color semantics.
- Keep hierarchy simple: status banner -> game cards -> secondary setup entry.
- Avoid dense admin dashboards on the home screen.

## 5. Setup and support screen

Setup screen:

- Remote Agent URL.
- Device name.
- Pairing code.
- Pair/refresh token/clear local token actions.
- Server reachability and auth guidance.
- User-facing display preferences such as diagnostic section visibility.
- Power readiness explanation and OpenSSH/setup details.
- Tailscale app binding status and host tailnet URL probing.
- SmartThings PAT input, PAT-only save path for already-known deviceId, `PC 켜기` device auto-selection, candidate selection, and manual deviceId fallback.
- Diagnostics and fake Remote Agent smoke guidance.

Power UI policy:

- Wake is enabled only after SmartThings PAT/OAuth authorization plus `PC 켜기` deviceId are present; deviceId is a target identifier and is never sufficient as SmartThings Cloud authorization.
- After pairing or online recovery, Android automatically creates/registers its SSH public key and runs marker-based SSH health.
- Sleep/restart/shutdown are enabled only after that automatic SSH registration/health chain succeeds.
- Restart/shutdown/sleep require a confirmation dialog; Wake may be one-tap.
- It must not call removed or host-managed power execution endpoints.

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
├── platform/TailscaleBinding.kt # app detection, launch/install, VPN-state adapter
└── ui/                          # Home, Setup, shared components
```

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

Required for setup:

- `POST /remote/pair/confirm`
- `POST /remote/tokens/refresh`
- `GET /remote/devices`
- `DELETE /remote/devices/{id}`

Required for automation setup:

- `POST /remote/tailscale/ensure`
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

Android reachability can start simple:

- HTTP status probe first.
- Friendly messages for timeout, DNS, connection refused, 401/403.
- Preserve last successful game snapshot.
- Add Tailscale-specific probes only after the core Home flow is stable.

## 10. Verification plan

Phase 0, rebuild scaffold:

```bash
./.venv/bin/python -m pytest tests/test_remote_android_client_static.py -q
cd remote_clients/android/HomeworkHelperRemote && ./gradlew :app:assembleDebug --stacktrace
./.venv/bin/python tools/check_android_apk_artifact.py
```

Phase 1, Home implementation:

- Static test for required v3 endpoints, icon payload fields, pull-to-refresh, and no stale power endpoints.
- Unit/static checks for token store and process card labels.
- APK build.
- Fake Remote Agent serves PNG process/resource icons from `assets/` and smoke verifies image endpoint hits.

Phase 2, physical device:

- Pairing and process-list sync on a real device.
- Cached game state survives app restart/offline host.
- Launch command accepted against a test Remote Agent.
- Usage Access/mobile-session checks only if those features are reintroduced.

## 11. Open questions for implementation phase

- Should Home include dashboard summary above or below game cards?
- Should Android v1 support Android-PC links immediately, or only after Home is stable?
- Which persistence API should replace SharedPreferences if settings grow: DataStore or simple SharedPreferences?
