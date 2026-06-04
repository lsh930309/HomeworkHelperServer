# HomeworkHelper Remote Client Setup Guide

Last refreshed: 2026-06-04

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

Public fixed-IP/domain access behind a router or reverse proxy:

```bash
HH_API_HOST=127.0.0.1 \
HH_API_PORT=8000 \
HH_REMOTE_PUBLIC_DIRECT=1 \
./.venv/bin/python homework_helper.pyw --server
```

Terminate HTTPS at the router, Caddy, nginx, or another local reverse proxy and
forward to the local HomeworkHelper server. Android public URLs must be
`https://...`; plain `http://...` is only for loopback, LAN, link-local, or
Tailscale `100.64.0.0/10` private routes.

### Public HTTPS direct path (manual port-forward v1)

Default topology:

```text
Android/macOS client
  -> https://211-216-28-65.sslip.io
  -> router WAN TCP 443
  -> Windows Host TCP 38443 (Caddy sidecar)
  -> http://127.0.0.1:8000 (HomeworkHelper Remote Agent)
```

Router rule to add manually:

| Purpose | Protocol | External port | Internal target | Internal port |
| --- | --- | ---: | --- | ---: |
| HomeworkHelper public HTTPS control plane | TCP | 443 | Windows Host fixed LAN IP | 38443 |

No UDP ports are required for the HomeworkHelper control plane. Do **not** forward
Remote Agent port `8000` directly to the internet. Sunshine/Apollo/Moonlight
streaming ports are a separate media-plane configuration and are not replaced by
this rule.

Client URL UX:

- Android and macOS accept the router public IPv4 address as input.
- `211.216.28.65` is normalized to `https://211-216-28-65.sslip.io`.
- Custom domains are allowed when entered as a full `https://...` URL.

Host-side Caddy sidecar default:

```caddyfile
{
    https_port 38443
    auto_https disable_redirects
}

https://211-216-28-65.sslip.io {
    reverse_proxy 127.0.0.1:8000
}
```

The Host App's Remote Settings dialog exposes `/remote/access/status` as a
readiness panel for public IP/hostname, router rule, Caddy status/config preview,
and UPnP diagnostics. UPnP auto-mapping is deliberately deferred in v1: the
current implementation performs read-only discovery only and keeps manual
port-forwarding as the safe baseline.

`--server` is a server-only entrypoint: it starts the FastAPI Remote Agent without entering the GUI single-instance/admin prompt path. SSH real-device test sessions can use the stricter `--testbench-server` variant through `tools/ssh_host_testbench.py`, which shadow-copies the installed package, assigns a per-session port/mutex/AppData root, writes a local report under `artifacts/ssh-host-testbench/`, and cleans the remote temp root after the run.

Security rules:

- Do not expose the Remote Agent publicly without bearer-token auth and HTTPS termination.
- For fixed-IP direct access, use `HH_REMOTE_PUBLIC_DIRECT=1`, bearer-token auth, and TLS termination through Caddy/router/reverse proxy.
- Tailscale remains a supported private-route fallback. It is not required when Android/macOS uses a public HTTPS Remote Agent URL.
- First-time Tailscale account creation, login, macOS VPN/System Extension approval, and any auth-key/MDM policy rollout remain explicit user/admin approval steps.
- `/remote/pair/start` is intended for loopback or trusted/authenticated setup. Android does not remotely issue the first pairing code; the user obtains it locally from the host and enters it on Android.
- `/remote/pair/confirm` accepts the local code from the client, but repeated failed guesses are rate-limited for the active pairing window.
- The host does not expose arbitrary shell or power-execution endpoints.
- If Tailscale/TCP is reachable but Remote Agent HTTP hangs or the Windows host app becomes sluggish, preserve the current state before restarting and follow `docs/remote/host-ssh-diagnostics-runbook.md`.
- For package-environment logic checks, prefer the isolated SSH testbench in `docs/remote/host-ssh-diagnostics-runbook.md` over probing or killing the production host process.

## 2. Pairing and tokens

1. Create a six-digit pairing code on the host:

```bash
curl -X POST http://127.0.0.1:8000/remote/pair/start
```

2. Enter Remote Agent URL, device name, and pairing code in the client.
3. Client calls `POST /remote/pair/confirm` and stores the returned device token.
4. Protected `/remote/*` endpoints use `Authorization: Bearer <token>`.
5. Android keeps the returned device token stable until explicit device revoke via `/remote/devices*`.

Token storage requirements:

- macOS: Keychain.
- Android rebuild: Android Keystore or equivalent platform secret storage.
- Plaintext preferences may store non-secret URL/device/UI settings only.

## 3. Shared Remote API surface

Core game-mirror and setup endpoints:

- `GET /remote/status`, `GET /remote/capabilities`, `GET /remote/readiness`
- `GET /remote/processes`, `POST /remote/processes/{id}/launch`, `POST /remote/processes/{id}/stop`
- `GET /remote/shortcuts`, `POST /remote/shortcuts/{id}/open`
- `GET /remote/dashboard/summary`
- `GET /remote/beholder/incidents`
- `GET /remote/game-links`, `POST /remote/game-links`
- `GET /remote/mobile-sessions/active`
- `POST /remote/mobile-sessions/start`, `POST /remote/mobile-sessions/end`
- `GET /remote/devices`, `DELETE /remote/devices/{id}`, `DELETE /remote/devices/revoked`
- `GET /remote/logging/config`, `PUT /remote/logging/config`
- `GET /remote/access/status`
- `GET /remote/power/status`, `GET /remote/power/setup`, `POST /remote/power/ssh-key`

Power boundary:

- The host reports readiness and registers SSH public keys.
- Wake/sleep/restart/shutdown are client-local side effects.
- Clients without a direct local power adapter must keep power buttons disabled.
- See `docs/remote/connection-supervisor-protocol.md` for power, OpenSSH, and SSH accepted-marker rules.

## 4. macOS client

Source: `remote_clients/macos/HomeworkHelperRemote`

```bash
swift build --package-path remote_clients/macos/HomeworkHelperRemote
./.venv/bin/python tools/package_macos_remote_app.py
open dist/macos/HomeworkHelperRemote.app
```

The macOS client is the reference native client. Its main UX is a menu-bar popover focused on registered game state, progress, running/today indicators, and quick host launch. Setup and diagnostics live in settings.

Architecture reference: `docs/remote/macos-client-architecture.md`.

## 5. Android client v3 game-first UX

Source: `remote_clients/android/HomeworkHelperRemote`

The old Android full-parity feature implementation was removed. The current Android v3 client uses a game-first Home tab plus a consolidated Setup tab. Home mirrors the macOS popover with host icons, resource icons, badges, quick launch/stop, pull-to-refresh, and a floating status message above bottom navigation. Setup is split into compact **연결/페어링 · 전원 · 기기 · 앱** sections for URL/pairing/stable token status, public HTTPS Connection Doctor, Tailscale optional fallback checks, Android-local power automation, device management, diagnostics, and fake smoke guidance.

Android-specific automation notes:

- The app does not send Tailscale VPN ON/OFF lifecycle broadcasts. Public HTTPS is the primary Remote Agent path; Tailscale can still be opened manually as a fallback.
- Wake uses SmartThings REST with PAT/OAuth authorization plus the `PC 켜기` target deviceId.
- Sleep/restart/shutdown use the Android OpenSSH adapter after key registration and health marker verification.
- Paired devices can be listed, revoked, and cleaned up from the Android Setup > 기기 section.

```bash
cd remote_clients/android/HomeworkHelperRemote
export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
export ANDROID_HOME=/opt/homebrew/share/android-commandlinetools
export ANDROID_SDK_ROOT=/opt/homebrew/share/android-commandlinetools
./gradlew :app:assembleRelease
```

Rebuild design: `docs/remote/android-client-design.md`.

## 6. Verification

Remote route/static checks:

```bash
./.venv/bin/python -m pytest tests/test_remote_routes.py
./.venv/bin/python -m pytest tests/test_remote_macos_client_static.py tests/test_remote_android_client_static.py
swift build --package-path remote_clients/macos/HomeworkHelperRemote
```

Android v3/internal checks:

```bash
./.venv/bin/python -m pytest tests/test_remote_android_client_static.py -q
cd remote_clients/android/HomeworkHelperRemote && ./gradlew :app:assembleRelease --stacktrace
./.venv/bin/python tools/check_android_apk_artifact.py
python tools/smoke_android_fake_remote.py --serial <adb-serial>
```

Fake Remote Agent smoke is the default development loop. Physical-device real-host verification remains a later release gate after fake-host UI/API contracts pass.
The fake smoke validates Home/Setup UI markers, PNG icon loading, launch/stop command acceptance, and token/device endpoint contracts before a real host is involved.

Stateful client smoke isolation contract:

- Client smokes must isolate local persistence from production user state.
- macOS ViewModel smoke must set `HH_REMOTE_CACHE_DIR`, `HH_REMOTE_PREFS_SUITE`, injected token store, and temporary power paths.
- Smoke fixtures may not write to production cache paths such as `~/Library/Application Support/HomeworkHelperRemote/cache/processes.json`.
- Tests that intentionally verify cache behavior must assert the production cache signature is unchanged.
- `tools/smoke_macos_connection_supervisor.py` validates the macOS supervisor state reducer.
- macOS connection-state scenarios remain documented in `docs/remote/macos-connection-state-scenarios.md`.
