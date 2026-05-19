# Android Remote Client Rebuild Design

Last refreshed: 2026-05-19
Status: Active rebuild design; existing Android feature code is legacy and should not be extended

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
- Prepare future Android-local power control without pretending it exists now.

Non-goals for the first rebuild pass:

- Full Android power side effects.
- Background sync, notifications, or WorkManager.
- Cloud relay or public Remote Agent exposure.
- Recreating every macOS settings option.
- Moonlight/Apollo integration.

## 3. UX structure

The Android home screen is the equivalent of the macOS popover.

Recommended navigation:

1. **Home / Games**: default screen, game mirror, quick launch, status feedback.
2. **Setup**: pairing, Remote Agent URL, auth recovery, connectivity guidance.
3. **More**: diagnostics, device management, Android-PC mobile-session tools, app settings.

If using bottom navigation, Home must be the first tab and remain selected after app launch. If using a single-screen layout for v1, Home content appears first and setup sections are below collapsible cards.

## 4. Home screen blueprint

Home header:

- App title and compact host status chip.
- Last sync time.
- Offline/stale/auth banner when needed.
- Manual refresh action.

Game list:

- Host-provided game icon when available; Material fallback when absent.
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

## 5. Setup and support screens

Setup screen:

- Remote Agent URL.
- Device name.
- Pairing code.
- Pair/refresh token/clear local token actions.
- Server reachability and auth guidance.

More/settings screen:

- Remote diagnostic logging toggle when implemented.
- Registered devices list and revoke/purge actions.
- Android-PC links and Usage Access tools, if retained in this rebuild.
- Power readiness explanation.

Power UI policy:

- Android must not show enabled wake/sleep/restart/shutdown buttons until Android-local direct adapters exist.
- It may show readiness/setup documentation and disabled buttons with explanatory copy.
- It must not call removed or host-managed power execution endpoints.

## 6. Android implementation architecture

Use a small, rebuild-friendly architecture:

```text
app/src/main/java/dev/homeworkhelper/remote/
├── MainActivity.kt              # Activity + top-level Compose scaffold
├── data/RemoteApiClient.kt      # low-level HTTP/JSON client for shared /remote/* contract
├── data/RemoteModels.kt         # DTOs and mapping helpers
├── data/RemoteRepository.kt     # snapshot fetch and commands
├── state/RemoteViewModel.kt     # UI state, refresh, pairing, launch commands
├── platform/TokenStore.kt       # Android Keystore token store
├── platform/Preferences.kt      # non-secret settings
├── platform/AndroidPlatform.kt  # browser/settings/package/Usage Access adapters
└── ui/                          # Home, Setup, More, shared components
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

Optional after Home is stable:

- `GET /remote/dashboard/summary`
- `GET /remote/beholder/incidents`
- `GET /remote/game-links`, `POST /remote/game-links`
- `GET /remote/mobile-sessions/active`, start/end mobile sessions
- `GET /remote/logging/config`, `PUT /remote/logging/config`
- `POST /remote/tailscale/ensure`
- `GET /remote/power/status`, `GET /remote/power/setup`, `POST /remote/power/ssh-key`

Do not use:

- `/remote/power/config`
- `/remote/power/{action}`
- `/remote/power/smartthings/devices`

Those belonged to older host-managed or macOS-local assumptions and are not valid Android v1 execution contracts.

## 8. Assets and icons

Preferred assets:

- Host process icon URLs from `/remote/processes`.
- Host resource icon URLs for progress/resource display.
- Material Icons/Material 3 default visual language for fallback status symbols.

Do not add a custom icon pack for v1. The visual quality target should come from layout, spacing, status color, typography, and good empty/error states.

Icon caching:

- Cache process icons only after the Home screen and API mapping are stable.
- Cache invalidation should be simple: process id + preferred size + URL/revision.

## 9. Connectivity model

Android should share the supervisor concepts from `REMOTE_CONNECTION_SUPERVISOR.md`:

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

- Static test for required v1 endpoints and no stale power endpoints.
- Unit/static checks for token store and process card labels.
- APK build.

Phase 2, physical device:

- Pairing and process-list sync on a real device.
- Cached game state survives app restart/offline host.
- Launch command accepted against a test Remote Agent.
- Usage Access/mobile-session checks only if those features are reintroduced.

## 11. Open questions for implementation phase

- Should Home include dashboard summary above or below game cards?
- Should Android v1 support Android-PC links immediately, or only after Home is stable?
- Which persistence API should replace SharedPreferences if settings grow: DataStore or simple SharedPreferences?
