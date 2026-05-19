# HomeworkHelper Remote Client Setup Guide

Last refreshed: 2026-05-19

HomeworkHelper exposes a local **Remote Agent** from the desktop app and controls it from native clients. The Remote Agent is local-first: it uses the existing FastAPI app, SQLite data, pairing tokens, and LAN/Tailscale-style private access rather than a hosted relay.

## 1. Remote Agent

Local development:

```bash
./.venv/bin/python homework_helper.pyw --server
```

Trusted LAN/tailnet device access:

```bash
HH_API_HOST=0.0.0.0 \
HH_API_PORT=8000 \
HH_REMOTE_REQUIRE_AUTH=1 \
./.venv/bin/python homework_helper.pyw --server
```

Security rules:

- Do not expose the Remote Agent publicly without bearer-token auth and a private network boundary.
- Prefer LAN firewall/Tailscale-style private routing over public port forwarding.
- `/remote/pair/start` is intended for loopback or trusted/authenticated setup.
- The host does not expose arbitrary shell or power-execution endpoints.

## 2. Pairing and tokens

1. Create a six-digit pairing code on the host:

```bash
curl -X POST http://127.0.0.1:8000/remote/pair/start
```

2. Enter Remote Agent URL, device name, and pairing code in the client.
3. Client calls `POST /remote/pair/confirm` and stores the returned device token.
4. Protected `/remote/*` endpoints use `Authorization: Bearer <token>`.
5. Token refresh and device revocation use `/remote/tokens/refresh` and `/remote/devices*`.

Token storage requirements:

- macOS: Keychain.
- Android rebuild: Android Keystore or equivalent platform secret storage.
- Plaintext preferences may store non-secret URL/device/UI settings only.

## 3. Shared Remote API surface

Core game-mirror and setup endpoints:

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
- `GET /remote/power/status`, `GET /remote/power/setup`, `POST /remote/power/ssh-key`

Power boundary:

- The host reports readiness and registers SSH public keys.
- Wake/sleep/restart/shutdown are client-local side effects.
- Clients without a direct local power adapter must keep power buttons disabled.
- See `REMOTE_CONNECTION_SUPERVISOR.md` for power, OpenSSH, and SSH accepted-marker rules.

## 4. macOS client

Source: `remote_clients/macos/HomeworkHelperRemote`

```bash
swift build --package-path remote_clients/macos/HomeworkHelperRemote
./.venv/bin/python tools/package_macos_remote_app.py
open dist/macos/HomeworkHelperRemote.app
```

The macOS client is the reference native client. Its main UX is a menu-bar popover focused on registered game state, progress, running/today indicators, and quick host launch. Setup and diagnostics live in settings.

Architecture reference: `docs/remote/macos-client-architecture.md`.

## 5. Android client v2 tabbed UX

Source: `remote_clients/android/HomeworkHelperRemote`

The old Android full-parity feature implementation was removed. The current Android v2 client uses bottom tabs: Home for game mirror and quick launch, Power for read-only readiness and disabled direct-power buttons, Setup for URL/pairing/token management, and More for diagnostics.

```bash
cd remote_clients/android/HomeworkHelperRemote
export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
export ANDROID_HOME=/opt/homebrew/share/android-commandlinetools
export ANDROID_SDK_ROOT=/opt/homebrew/share/android-commandlinetools
./gradlew :app:assembleDebug
```

Rebuild design: `docs/remote/android-client-design.md`.

## 6. Verification

Remote route/static checks:

```bash
./.venv/bin/python -m pytest tests/test_remote_routes.py
./.venv/bin/python -m pytest tests/test_remote_macos_client_static.py tests/test_remote_android_client_static.py
swift build --package-path remote_clients/macos/HomeworkHelperRemote
```

Android v2/internal checks:

```bash
./.venv/bin/python -m pytest tests/test_remote_android_client_static.py -q
cd remote_clients/android/HomeworkHelperRemote && ./gradlew :app:assembleDebug --stacktrace
./.venv/bin/python tools/check_android_apk_artifact.py
python tools/smoke_android_fake_remote.py --serial <adb-serial>
```

Fake Remote Agent smoke is the default development loop. Physical-device real-host verification remains a later release gate after fake-host UI/API contracts pass.

Stateful client smoke isolation contract:

- Client smokes must isolate local persistence from production user state.
- macOS ViewModel smoke must set `HH_REMOTE_CACHE_DIR`, `HH_REMOTE_PREFS_SUITE`, injected token store, and temporary power paths.
- Smoke fixtures may not write to production cache paths such as `~/Library/Application Support/HomeworkHelperRemote/cache/processes.json`.
- Tests that intentionally verify cache behavior must assert the production cache signature is unchanged.
- `tools/smoke_macos_connection_supervisor.py` validates the macOS supervisor state reducer.
- macOS connection-state scenarios remain documented in `docs/remote/macos-connection-state-scenarios.md`.
