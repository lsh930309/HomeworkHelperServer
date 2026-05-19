# HomeworkHelper Remote Android

Status: Home/Games MVP. The previous Android full-parity implementation has been removed to avoid extending the wrong architecture.

The Android client is being rebuilt from `docs/remote/android-client-design.md`. The current MVP makes the Android home screen mirror the macOS popover: registered game status, progress, running/today indicators, quick host launch, and minimal pairing/setup are the primary UX. Power readiness, device management, Android-PC links, and diagnostics remain supporting surfaces for later phases.

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

## Build MVP

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
- `REMOTE_CONNECTION_SUPERVISOR.md` — shared pairing, connectivity, power, OpenSSH, and SSH protocol rules.

Do not resurrect the deleted Android full-parity code. Rebuild Home/Games first, then add setup/support surfaces only as needed.
