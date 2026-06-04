# HomeworkHelper Remote Client Setup Guide

Last refreshed: 2026-06-04

HomeworkHelper exposes a local **Remote Agent** from the desktop app and controls it from native Android/macOS clients. The active external-network design is **공개 HTTPS 직접접속** with **수동 포트포워딩**. Clients ask the user for the **공유기 WAN 공인 IPv4** only and derive the actual URL internally.

## 1. Remote Agent startup

Local development:

```bash
./.venv/bin/python homework_helper.pyw --server
```

Public fixed-IP access behind the router/Caddy sidecar:

```bash
HH_API_HOST=127.0.0.1 HH_API_PORT=8000 HH_REMOTE_PUBLIC_DIRECT=1 ./.venv/bin/python homework_helper.pyw --server
```

Security baseline:

- Public direct mode must use HTTPS and bearer-token auth.
- `Remote Agent 8000` remains local behind Caddy/reverse proxy.
- Do not forward `8000` directly to the internet.

## 2. Public HTTPS direct path

Default topology:

```text
Android/macOS client
  → https://211-216-28-65.sslip.io
  → router WAN TCP 443
  → Windows Host TCP 38443 (Caddy sidecar)
  → http://127.0.0.1:8000 (HomeworkHelper Remote Agent)
```

Router rule to add manually:

| Purpose | Protocol | External port | Internal target | Internal port |
| --- | --- | ---: | --- | ---: |
| HomeworkHelper public HTTPS control plane | TCP | 443 | Windows Host fixed LAN IP | 38443 |

No UDP ports are required for the HomeworkHelper control plane. Sunshine/Apollo/Moonlight streaming ports are a separate media-plane configuration and are not replaced by this rule.

Client URL UX:

- Android and macOS accept only the router public IPv4 address in the primary setup field.
- `211.216.28.65` is normalized to `https://211-216-28-65.sslip.io` internally.
- URL, port, LAN/private, loopback, link-local, and CGNAT values are rejected in the normal UX.

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

The Host App's Remote Settings dialog exposes `/remote/access/status` for public IP/hostname, router rule, Caddy status/config preview, warnings, and advisories. Automatic router mapping is deferred; the supported path is manual forwarding.

## 3. Pairing and tokens

1. Create a six-digit pairing code on the host:

```bash
curl -X POST http://127.0.0.1:8000/remote/pair/start
```

2. Enter the router public IPv4, device name, and pairing code in the client.
3. Client calls `POST /remote/pair/confirm` and stores the returned device token.
4. Protected `/remote/*` endpoints use `Authorization: Bearer <token>`.
5. Android/macOS keep the returned token stable until explicit device revoke.

Token storage requirements:

- macOS: Keychain.
- Android: Android Keystore or equivalent platform secret storage.
- Plain preferences may store non-secret public IP/device/UI settings only.

## 4. Shared Remote API surface

Core endpoints:

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
- `GET /remote/power/status`, `GET /remote/power/setup`
- `POST /remote/power/actions/{sleep|restart|shutdown}`

Power boundary:

- **Wake는 SmartThings**: the client sends SmartThings commands to the configured `PC 켜기` device and does not depend on host HTTP availability.
- **Host HTTPS 위임**: sleep/restart/shutdown are delegated to the host Remote Agent over authenticated HTTPS after `/remote/power/status` advertises support.
- Unsupported actions remain disabled in clients.

## 5. macOS client

Source: `remote_clients/macos/HomeworkHelperRemote`

```bash
swift build --package-path remote_clients/macos/HomeworkHelperRemote
./.venv/bin/python tools/package_macos_remote_app.py
open dist/macos/HomeworkHelperRemote.app
```

Architecture reference: `docs/remote/macos-client-architecture.md`.

## 6. Android client v3 game-first UX

Source: `remote_clients/android/HomeworkHelperRemote`

Android Home mirrors the macOS popover: host game icons, resource icons, quick launch/stop, pull-to-refresh, cached offline state, and floating status. Setup contains compact **연결/페어링 · 전원 · 기기 관리 · 앱 동작** sections for public-IP pairing, Connection Doctor, SmartThings Wake, Host HTTPS delegated power, device management, diagnostics, and fake smoke guidance.

```bash
cd remote_clients/android/HomeworkHelperRemote
export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
export ANDROID_HOME=/opt/homebrew/share/android-commandlinetools
export ANDROID_SDK_ROOT=/opt/homebrew/share/android-commandlinetools
./gradlew :app:assembleRelease
```

Rebuild design: `docs/remote/android-client-design.md`.

## 7. Verification

Recommended checks after remote-connectivity changes:

```bash
PYTHONPATH=src ./.venv/bin/python -m pytest   tests/test_build_android_remote.py   tests/test_remote_android_client_static.py   tests/test_remote_macos_client_static.py   tests/test_remote_routes.py -q
swift build --package-path remote_clients/macos/HomeworkHelperRemote
cd remote_clients/android/HomeworkHelperRemote && ./gradlew :app:compileReleaseKotlin
```
