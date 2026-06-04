# HomeworkHelper Remote Android

Status: v3 game-first UX active implementation.

The Android client follows `docs/remote/android-client-design.md`. The current app has two bottom tabs: Home mirrors the macOS popover with registered game status, host/resource icons, progress, badges, quick launch/stop, pull-to-refresh, and a floating status message; Setup owns public-IP pairing, token status, Connection Doctor, SmartThings Wake, Host HTTPS delegated power, paired-device management, diagnostics, and fake Remote Agent smoke guidance.

## Preserved project contract

- Package: `dev.homeworkhelper.remote`
- Stack: Kotlin, Jetpack Compose, Material 3
- Gradle wrapper: 9.5.0
- Android Gradle Plugin: 8.13.0
- Kotlin: 2.2.21
- Compose BOM: 2026.03.00
- minSdk: 26
- targetSdk: 36
- Manifest permissions retained: `INTERNET`, `PACKAGE_USAGE_STATS`

## Build v3

```bash
cd remote_clients/android/HomeworkHelperRemote
export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
export ANDROID_HOME=/opt/homebrew/share/android-commandlinetools
export ANDROID_SDK_ROOT=/opt/homebrew/share/android-commandlinetools
./gradlew :app:assembleRelease
```

The APK is produced at `app/build/outputs/apk/release/app-release.apk`.

## Wireless ADB build/install helper

The repository root has `build_android_remote.py` for the host-side release loop:

```bash
./.venv/bin/python build_android_remote.py --host-url 211.216.28.65
```

`--host-url` accepts the router public IPv4. The helper seeds the release build with the internally derived `https://211-216-28-65.sslip.io` URL. For adb installation, pass `--device-ip` or `--serial` when needed. The Android client itself is a lightweight direct-connection app: no embedded private-network bridge is generated.

The helper signs APKs with a stable local keystore at `local-artifacts/android-signing/homeworkhelper-android-debug.keystore` (untracked). If an older app was signed with a different debug key, the default is a safe failure. For the one-time migration where app data loss is acceptable:

```bash
./.venv/bin/python build_android_remote.py --uninstall-on-signature-mismatch
```

## Implementation source of truth

- `docs/remote/macos-client-architecture.md` — reference macOS client behavior and contracts.
- `docs/remote/android-client-design.md` — Android rebuild UX/system design.
- `docs/remote/connection-supervisor-protocol.md` — shared pairing, connectivity, power, and public HTTPS rules.

Do not resurrect the deleted Android full-parity code. Keep Home/Games first and keep setup/support surfaces compact.

## Fake Remote Agent smoke

During Android iteration, prefer fake host validation before real-host pairing:

```bash
python3 tools/smoke_android_fake_remote.py --serial <adb-serial>
```

The smoke uses `adb reverse`, a local fake `/remote/*` server, uiautomator markers, launch/stop command checks, token/device endpoint checks, PNG icon hits, and screenshots under `artifacts/android-device/`.

## Setup hierarchy and automation

- **연결/페어링**: 공유기 공인 IP, device name, pairing code, stable token status, Connection Doctor, direct system-route status.
- **전원**: SmartThings PAT/device selection for Wake plus Host HTTPS 위임 readiness for sleep/restart/shutdown.
- **기기 관리**: paired-device refresh, revoke, and revoked-device cleanup.
- **앱 동작**: diagnostics toggle and fake smoke guidance.

The primary path is **공개 HTTPS 직접접속**:

```text
Android client
  → https://<공인IP-대시>.sslip.io
  → 공유기 WAN TCP 443
  → Windows Host TCP 38443
  → Caddy
  → Remote Agent 8000 on loopback
```

Router rule: **TCP 443 → Windows Host 38443**. Do not expose `Remote Agent 8000` directly. No UDP port is required for the HomeworkHelper control plane.

## Local SmartThings wake defaults

The debug build can have a personal default wake target for `PC 켜기` baked into BuildConfig. The `deviceId` selects the target only; SmartThings REST still requires an authenticated actor.

Secrets must stay out of git: prefer `local-artifacts/secrets/SmartThings_Token`, or use an untracked `local.properties` override only when building a private APK.

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
