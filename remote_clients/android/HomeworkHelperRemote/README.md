# HomeworkHelper Remote Android

Status: v3 game-first UX active implementation. The previous Android full-parity implementation has been removed to avoid extending the wrong architecture.

The Android client follows `docs/remote/android-client-design.md`. The current v3 shape uses two bottom tabs: Home mirrors the macOS popover with registered game status, host/resource icons, server-tracked/projection-aware resource progress, badges, quick launch/stop, pull-to-refresh, and a floating status message; Setup owns pairing/URL/token inputs, Tailscale foundation and lifecycle options, Android-local power automation, paired-device management, diagnostics, and fake Remote Agent smoke guidance.

## Preserved project contract

- Package: `dev.homeworkhelper.remote`
- Stack: Kotlin, Jetpack Compose, Material 3
- Gradle wrapper: 9.5.0
- Android Gradle Plugin: 8.13.0
- Kotlin: 2.2.21
- Compose BOM: 2026.03.00
- minSdk: 26
- targetSdk: 36
- Manifest permissions retained for the rebuild: `INTERNET`, `PACKAGE_USAGE_STATS`

## Build v3

```bash
cd remote_clients/android/HomeworkHelperRemote
export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
export ANDROID_HOME=/opt/homebrew/share/android-commandlinetools
export ANDROID_SDK_ROOT=/opt/homebrew/share/android-commandlinetools
./gradlew :app:assembleDebug
```

The APK is still produced at `app/build/outputs/apk/debug/app-debug.apk`.

## Implementation source of truth

- `docs/remote/macos-client-architecture.md` — reference macOS client behavior and contracts.
- `docs/remote/android-client-design.md` — Android rebuild UX/system design.
- `docs/remote/connection-supervisor-protocol.md` — shared pairing, connectivity, power, OpenSSH, and SSH protocol rules.

Do not resurrect the deleted Android full-parity code. Rebuild Home/Games first, then add setup/support surfaces only as needed.

## Fake Remote Agent smoke

During Android iteration, prefer fake host validation before real-host pairing:

```bash
python tools/smoke_android_fake_remote.py --serial <adb-serial>
```

The smoke uses `adb reverse`, a local fake `/remote/*` server, uiautomator markers, launch/stop command checks, token/device endpoint checks, PNG icon hits, and screenshots under `artifacts/android-device/`.

## Setup hierarchy and automation

Setup is intentionally compact and mirrors the macOS settings hierarchy where Android has an equivalent:

- **연결/페어링**: Remote Agent URL, device name, pairing code, stable device token status, Tailscale install/open/status, Android-local VPN readiness check, and VPN ON request.
- **전원**: readiness, OpenSSH key/health setup, SmartThings PAT/OAuth and `PC 켜기` device auto-selection.
- **기기**: paired-device refresh, revoke, and revoked-device cleanup.
- **앱**: diagnostics toggle, optional Tailscale ON at app foreground, optional Tailscale OFF at app background, and manual VPN ON/OFF requests.

Tailscale automation requests the installed Tailscale Android app to connect/disconnect VPN, polls Android-local VPN state, and only then refreshes the host snapshot. The Android client does not call host-side Tailscale ensure/health mutation endpoints.


## Local SmartThings wake defaults

The debug build has a personal default wake target for `PC 켜기` baked into BuildConfig.
The `deviceId` selects the target only; SmartThings REST still requires an authenticated actor.
Secrets must stay out of git: prefer `local-artifacts/secrets/SmartThings_Token`, or use an untracked `local.properties` override only when building a private APK.

SmartThings CLI can reuse an existing login or a PAT, but it does not mint PATs from the command line.
Generate a short-lived PAT at `https://account.smartthings.com/tokens`, then either paste it into the Android app or keep it local for a private debug APK.
The checked-in Gradle script reads `smartthings.pat` from Android `local.properties` first, then `local-artifacts/secrets/SmartThings_Token`, then legacy Android-project/repository-root `SmartThings_Token` files.
For one-off CLI verification:

```bash
smartthings devices --token "$SMARTTHINGS_PAT"
smartthings devices:commands 145ad447-9969-4ee7-bda0-1760430d9be1 'switch:on' --token "$SMARTTHINGS_PAT"
```

```properties
smartthings.deviceId=145ad447-9969-4ee7-bda0-1760430d9be1
smartthings.deviceLabel=PC 켜기
smartthings.locationId=7bbf137d-1f96-4ad4-9e39-1cdab082d41a
smartthings.pat= # optional local-only debug token; never commit a real value
```
