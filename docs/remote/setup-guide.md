# HomeworkHelper Remote Client Setup Guide

Last refreshed: 2026-05-17

HomeworkHelper can expose a local **Remote Agent** from the desktop app and control it from native macOS and Android clients. The Remote Agent is still local-first: it uses the existing FastAPI app, SQLite data, pairing tokens, and optional Tailscale/LAN access rather than a hosted relay.

## 1. Remote Agent

For local development, start the server on loopback:

```bash
./.venv/bin/python homework_helper.pyw --server
```

Defaults:

- host: `127.0.0.1`
- port: `8000`
- auth: disabled only when no paired device and no explicit remote token exist

For remote devices on a trusted LAN/tailnet, bind the agent to all interfaces and require auth:

```bash
HH_API_HOST=0.0.0.0 \
HH_API_PORT=8000 \
HH_REMOTE_REQUIRE_AUTH=1 \
./.venv/bin/python homework_helper.pyw --server
```

Security rules:

- Do not expose the Remote Agent to a public interface without Bearer-token auth.
- Prefer Tailscale or a private LAN firewall rule over port-forwarding.
- `/remote/pair/start` is intended for loopback or already-authenticated requests.
- Remote power endpoints accept fixed action enums only; they do not accept arbitrary shell commands.

## 2. Pairing and tokens

1. Create a six-digit pairing code on the host:

```bash
curl -X POST http://127.0.0.1:8000/remote/pair/start
```

2. Enter the Remote Agent URL, device name, and pairing code in the macOS or Android client.
3. The client calls `POST /remote/pair/confirm` and stores the returned device token.
4. Once a device is registered, protected `/remote/*` endpoints require `Authorization: Bearer <token>`.
5. Use the client device-management screen to refresh, revoke, or purge tokens.

Token storage:

- macOS: Keychain service/account boundary in `KeychainTokenStore.swift`.
- Android: Android Keystore AES/GCM storage in `AndroidTokenStore.kt`; legacy plaintext preference migration is removed after first successful migration.
- Host-local device registry and power settings live under the remote-local store described in `docs/remote/remote-storage-policy.md`.

## 3. Remote API surface

The native clients share these Remote Agent contracts:

- `GET /remote/status`, `GET /remote/capabilities`, `GET /remote/readiness`
- `POST /remote/tokens/refresh`
- `GET /remote/processes`, `POST /remote/processes/{id}/launch`
- `GET /remote/shortcuts`, `POST /remote/shortcuts/{id}/open`
- `GET /remote/dashboard/summary`
- `GET /remote/beholder/incidents`
- `GET /remote/game-links`, `POST /remote/game-links`
- `GET /remote/mobile-sessions/active`
- `POST /remote/mobile-sessions/start`, `POST /remote/mobile-sessions/end`
- `GET /remote/devices`, `DELETE /remote/devices/{id}`, `DELETE /remote/devices/revoked`
- `GET /remote/logging/config`, `PUT /remote/logging/config`
- `POST /remote/tailscale/ensure`
- `GET /remote/power/status`, `GET /remote/power/config`, `PUT /remote/power/config`
- `GET /remote/power/setup`, `POST /remote/power/ssh-key`, `POST /remote/power/smartthings/devices`
- `POST /remote/power/{wake|sleep|restart|shutdown}`

## 4. macOS client

Source: `remote_clients/macos/HomeworkHelperRemote`

Build and package:

```bash
swift build --package-path remote_clients/macos/HomeworkHelperRemote
./.venv/bin/python tools/package_macos_remote_app.py
open dist/macos/HomeworkHelperRemote.app
```

Current macOS capabilities:

- menu-bar-first SwiftUI/AppKit app with Liquid Glass UI target
- Keychain token storage, token refresh, revoke, and local pairing clear
- Remote Agent status, process launch, dashboard summary, Beholder read-only cards
- Android-PC game-link creation and manual mobile-session control
- Tailscale discovery/ensure helpers
- remote desktop logging toggle
- power setup, SSH key registration, SmartThings device probe, power config save, and capability-gated power commands
- process/resource icon caching and configurable menu-bar icon, summary visibility, progress display, popover transparency, and polling interval

## 5. Android client

Source: `remote_clients/android/HomeworkHelperRemote`

Build:

```bash
cd remote_clients/android/HomeworkHelperRemote
export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
export ANDROID_HOME=/opt/homebrew/share/android-commandlinetools
export ANDROID_SDK_ROOT=/opt/homebrew/share/android-commandlinetools
./gradlew :app:assembleDebug
```

Current Android baseline:

- Kotlin + Jetpack Compose native app
- Android Gradle Plugin 8.13.0, Kotlin 2.2.21, Compose BOM 2026.03.00, Gradle 9.5.0
- package `dev.homeworkhelper.remote`, minSdk 26, targetSdk 36
- Android Keystore token storage and legacy token migration
- Remote status/process/shortcut/device/dashboard/Beholder/power/game-link/mobile-session API coverage
- Android package launch via launcher intent and package visibility queries
- Usage Access entry point, recent foreground app lookup, and game-link based `usage_stats` mobile-session sync

The full-parity target and implementation sequence are documented in `docs/remote/android-client-design.md`.

## 6. Verification

General remote checks:

```bash
./.venv/bin/python -m pytest tests/test_remote_routes.py
./.venv/bin/python -m pytest tests/test_remote_macos_client_static.py tests/test_remote_android_client_static.py
swift build --package-path remote_clients/macos/HomeworkHelperRemote
./.venv/bin/python tools/verify_remote_controller.py --skip-full-pytest
```

Android checks are split into two automated stages.

Stage 1, internal tests without a device:

```bash
./.venv/bin/python tools/verify_android_internal.py
```

Stage 2, after connecting one USB-debuggable physical Android device:

```bash
./.venv/bin/python tools/verify_android_device.py
# or, when multiple devices are connected
./.venv/bin/python tools/verify_android_device.py --device <adb-serial>
```

The device stage installs and launches the APK, reports UsageStats appop state, starts a temporary Remote Agent, uses `adb reverse` so no emulator or LAN IP is required, types the Android app's Remote Agent URL, pairs with a generated code, syncs data, verifies mobile-session/UsageStats behavior, and checks Android Keystore token persistence after app restart.

Individual smoke entry points remain available for debugging:

```bash
./.venv/bin/python tools/smoke_remote_controller_runtime.py
./.venv/bin/python tools/smoke_macos_remote_api_client.py
./.venv/bin/python tools/smoke_macos_remote_viewmodel.py
./.venv/bin/python tools/check_android_sdk_readiness.py
./.venv/bin/python tools/check_android_apk_artifact.py
./.venv/bin/python tools/smoke_android_remote_controller.py --report-usage-access
./.venv/bin/python tools/smoke_android_remote_e2e.py --adb-reverse --android-base-url http://127.0.0.1:8000
```

Stateful client smoke isolation contract:

- Any smoke that compiles or launches production client code must isolate every local persistence boundary, not just the temporary server.
- macOS ViewModel smoke must set `HH_REMOTE_CACHE_DIR` for `RemoteClientCache`, `HH_REMOTE_PREFS_SUITE` for `UserDefaults`, an injected in-memory token store for Keychain-equivalent secrets, and temporary SSH/SmartThings paths for local power setup.
- Smoke fixtures such as `Smoke Game` may never be written to production cache paths like `~/Library/Application Support/HomeworkHelperRemote/cache/processes.json`.
- Tests that intentionally verify local cache behavior must also assert the production cache signature is unchanged before reporting success.
- If a new client smoke touches persistence, add an override hook first and lock it with a static test before adding the behavior assertion.

External connectivity check against an already-running host:

```bash
./.venv/bin/python tools/smoke_remote_controller_connectivity.py \
  --base-url http://<host-or-tailnet-ip>:8000 \
  --token "<paired-device-token>" \
  --expect-auth
```

Before release, `tools/verify_android_internal.py` and `tools/verify_android_device.py` must both pass; emulator coverage is optional supplementary evidence.
