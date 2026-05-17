# Android Remote Client Full-Parity Design

Last refreshed: 2026-05-17
Status: Active design for completing the Android client from the existing Kotlin/Compose baseline

## 1. Goal

Build the Android Remote Client as a native counterpart to the completed macOS Remote Client. Full parity means Android exposes the same user-facing HomeworkHelper remote-control jobs through Android-native UI and platform integrations, while keeping the shared Remote Agent API contract stable.

Success criteria:

- A user can pair Android with the Remote Agent, recover or refresh the token, and manage registered devices without using curl.
- Android can inspect host readiness, launch PC games, open web shortcuts, show play summary and Beholder read-only alerts, and run supported power commands with capability gating.
- Android can map PC processes to Android packages, launch the matching Android app, and record manual or UsageStats-driven mobile sessions into the same dashboard metrics as macOS/host.
- Android explains offline/auth/power/Usage Access states in the UI instead of failing silently.
- Android verification is split into two automated stages: device-free internal tests and physical-device tests run after connecting a USB-debuggable Android device.
- The physical-device stage uses scripts, adb install/launch, adb reverse, pairing automation, Keystore persistence checks, Usage Access appop setup/reporting, package launch, and mobile-session sync without requiring an emulator.

Non-goals for this design:

- Do not rename or reshape existing `/remote/*` endpoints.
- Do not add a cloud relay, push channel, or new dependency unless a later release explicitly chooses it.
- Do not copy macOS-only concepts literally. Menu bar, Dock reopen, and SF Symbol picker become Android-native entry points/settings.

## 2. Current baseline

Existing Android project: `remote_clients/android/HomeworkHelperRemote`

Observed baseline:

- Build: Android Gradle Plugin 8.13.0, Kotlin 2.2.21, Compose BOM 2026.03.00, Gradle wrapper 9.5.0.
- Runtime package: `dev.homeworkhelper.remote`, minSdk 26, targetSdk 36.
- Storage: `RemotePreferences` for non-secret settings, `AndroidTokenStore` for Android Keystore AES/GCM token storage.
- API: `RemoteApiClient` covers status, capabilities, dashboard summary, Beholder incidents, game-links, mobile sessions, processes, shortcuts, power config/control, pairing, token refresh, and devices.
- Platform integration: `AndroidIntegration` handles package launch intent, Usage Access settings, appop check, and recent foreground app query.
- UI: `MainActivity.kt` contains a single Compose screen with connection, pairing, status, power, Android local launch, dashboard, Beholder, Android-PC links, process, shortcut, and device sections.

This is functional as a vertical slice, but the UI/state architecture is still prototype-shaped. Full parity should harden it without changing the host API contract.

## 3. Full-parity matrix

| Capability | macOS baseline | Android full-parity target | Current Android state | Required work |
| --- | --- | --- | --- | --- |
| Pairing/token | Keychain token, pair, refresh, revoke, clear local token, auto setup messaging | Keystore token, pair, refresh, revoke, clear local token, recovery messaging | Mostly present | Add recovery/status UX and separate token/device screens |
| Host readiness | Status, capabilities, readiness, Tailscale ensure, setup progress | Same information with Android-native status cards | Partial status/capability display | Add readiness endpoint display and clearer auth/offline states |
| Process control | Process list with icons/progress and PC launch | Process list with icons/progress and PC launch | Basic process list and launch | Add icon/resource cache, progress display, and disabled/error states |
| Web shortcuts | List and open host shortcuts | Same | Present | Add empty/error/loading states |
| Dashboard | Play summary and mobile metrics | Same | Present | Improve visual hierarchy and refresh states |
| Beholder | Read-only incident card | Same | Present | Add severity styling and empty state |
| Android-PC links | Create link, manual mobile start/end | Create link, Android package launch, manual start/end, link management | Present | Add edit/delete affordance if host API supports it later; keep create-only until then |
| UsageStats sync | N/A as a macOS platform feature; Android-specific extension is already in shared data model | Permission-guided automatic start/end based on foreground package | Present as manual sync button | Add persistent periodic/manual sync policy and explicit permission diagnostics |
| Power config/control | SSH/SmartThings setup helpers and capability-gated buttons | Capability-gated buttons, config save, setup/readiness display | Basic config/control present | Add setup/readiness display and safer validation copy |
| Tailscale/connectivity | Discovery and server ensure helpers | URL entry plus connectivity check; Tailscale app deep link/instructions if needed | Basic URL entry only | Add connectivity diagnostics without requiring new dependency |
| Diagnostic logging | Toggle host/client desktop logging | Toggle host logging and Android local log export/share | Host logging config not surfaced well | Add log toggle and local share/export design |
| App settings | Login item, summary toggle, poll interval, progress mode, popover transparency, menu-bar icon | Summary toggle, refresh interval, progress mode, theme/system settings, clear cache | Not separated | Add Settings screen and persist non-secret preferences |
| Verification | Swift build, API/ViewModel smoke, static tests | Two-stage automated workflow: internal device-free gate, then physical-device gate | Static/build/APK checks and adb/e2e scripts exist | Keep `tools/verify_android_internal.py` and `tools/verify_android_device.py` as the required entry points |

## 4. Target architecture

Keep the existing package and API model files, but split responsibilities before adding more parity UI.

Recommended module shape:

```text
app/src/main/java/dev/homeworkhelper/remote/
├── MainActivity.kt                 # Activity and top-level Compose host only
├── RemoteAppViewModel.kt           # state machine, refresh, commands, pairing, messages
├── RemoteRepository.kt             # RemoteApiClient orchestration and snapshot fetches
├── RemoteApiClient.kt              # low-level HTTP/JSON contract; keep endpoint names stable
├── RemoteModels.kt                 # DTOs matching snake_case Remote Agent payloads
├── AndroidTokenStore.kt            # secret token storage
├── RemotePreferences.kt            # base URL, device name, UI settings, poll interval
├── AndroidIntegration.kt           # package launch and UsageStats integration
├── ui/                             # Compose screens and section components
└── verification/ or androidTest/    # future instrumentation helpers when added
```

State model:

- `RemoteAppState` owns base URL, pairing code, token presence, loading/error message, host status, dashboard summary, incidents, game links, sessions, processes, shortcuts, devices, power config, readiness, usage snapshot, and settings.
- `RemoteAppViewModel.refresh()` performs one snapshot fetch for status, dashboard, incidents, links, sessions, power config, processes, shortcuts, and optionally devices.
- Commands return user-visible messages and then refresh the affected snapshot.
- Auth failures should mark the state as `authRejected` and show pairing/token recovery actions.
- Network failures should preserve the last successful snapshot and show an offline banner.

Refresh policy:

- Default to manual refresh plus a persisted polling interval, matching the macOS hybrid polling direction.
- Poll only while the app is foregrounded for v1.
- Defer background sync/WorkManager until there is a concrete need for notifications or unattended UsageStats sync.

## 5. UX blueprint

Use Material 3 and keep the first release simple:

1. **Connection screen/state**
   - Remote Agent URL, device name, pairing code, pair button.
   - Token present/absent indicator, refresh token, clear local token.
   - Last connection result and auth/offline guidance.

2. **Dashboard tab**
   - Host status/readiness card.
   - Play summary and mobile metrics.
   - Beholder read-only alerts.
   - Quick actions: refresh, PC wake/sleep/restart/shutdown when supported.

3. **Library tab**
   - Process cards with icon/progress/PC launch.
   - Web shortcut cards.
   - Empty and loading states.

4. **Android-PC tab**
   - Game-link create form using PC process ID and Android package.
   - Linked app list with Android launch and mobile start/end.
   - Usage Access status, open-settings action, recent foreground app, and sync action.

5. **Settings tab**
   - Token/device management.
   - Power config and readiness display.
   - Remote diagnostic logging toggle.
   - Refresh interval, dashboard summary visibility, progress display mode, clear cache.

## 6. Platform policies

- **Cleartext HTTP**: keep `usesCleartextTraffic=true` for private LAN/tailnet Remote Agent use. Revisit if public distribution or HTTPS support is added.
- **Usage Access**: request by explanation and settings deep link only. The permission cannot be granted from the manifest alone.
- **Package visibility**: launcher intent query remains broad enough for package launch. Avoid hardcoding game package lists.
- **Keystore**: token operations must continue through `AndroidTokenStore`; no Bearer token writes to plaintext preferences.
- **Power commands**: Android must use `RemoteStatus.isPowerActionEnabled(action)` or equivalent gating before enabling buttons.
- **Local logs**: if Android log export is added, avoid storing tokens or full Authorization headers.

## 7. Implementation sequence

1. Lock current behavior with static tests for existing API endpoints, Keystore markers, UsageStats markers, and Compose labels.
2. Extract `RemoteAppViewModel`, `RemoteRepository`, and Compose section components without changing visible behavior.
3. Add readiness/auth/offline state handling and clearer connection recovery messages.
4. Add icon/resource cache and progress display parity for process cards.
5. Split screens/tabs and add Settings/device/power/logging controls.
6. Harden UsageStats sync policy and diagnostics.
7. Keep verification as a two-stage workflow: run internal tests first, then run the physical-device script after connecting a USB-debuggable Android device. Emulator e2e remains optional, not the default release gate.

## 8. Verification workflow

Android verification has exactly two default stages. Use an emulator only when reproducing emulator-specific behavior or when CI cannot attach a physical device.

### Stage 1 — Internal tests, no Android runtime

Run this on every Android client change before touching a device:

```bash
./.venv/bin/python tools/verify_android_internal.py
```

The script runs:

1. `pytest tests/test_remote_android_client_static.py` for API, Keystore, UsageStats, manifest, docs, and script contract markers.
2. `tools/check_android_sdk_readiness.py` for SDK/package/license readiness.
3. `./gradlew :app:assembleDebug --stacktrace` for Kotlin/Compose build.
4. `tools/check_android_apk_artifact.py` for APK package/version/SDK/permission contract.

This stage proves the APK can be built and has the expected contract, but it does not prove Android runtime behavior.

### Stage 2 — Physical-device automated tests

Connect one Android device with USB debugging enabled, then run:

```bash
./.venv/bin/python tools/verify_android_device.py
```

If multiple devices are connected:

```bash
./.venv/bin/python tools/verify_android_device.py --device <adb-serial>
```

The script runs:

1. `tools/smoke_android_remote_controller.py --report-usage-access` to install the APK, launch `MainActivity`, confirm package installation, and report UsageStats appop state.
2. `tools/smoke_android_remote_e2e.py --adb-reverse --android-base-url http://127.0.0.1:<port>` to start a temporary Remote Agent, reverse the device port to the host, type the Remote Agent URL into the app, pair with a generated code, sync data, start/end mobile sessions, run UsageStats sync, force-stop/restart the app, and verify encrypted token persistence.

Release criteria for Android parity:

- Stage 1 passes.
- Stage 2 passes on a physical Android device.
- Power buttons remain capability-gated and do not fire unsupported side-effect commands.
- Any emulator run is optional supplementary evidence, not a replacement for the physical-device gate.
