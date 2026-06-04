# Remote Connection Supervisor, Pairing, and Power Protocol

Last refreshed: 2026-06-04
Status: Shared protocol reference for macOS and Android clients

## 1. Purpose

This document defines the shared HomeworkHelper Remote connectivity protocol. The active external-network model is **공개 HTTPS 직접접속** with **수동 포트포워딩**. The supervisor itself is a reducer: it accepts typed evidence and returns UI state, reconnect guidance, and payload-sync hints. It never performs HTTP, SmartThings, AppKit, Android, or shell side effects directly.

## 2. Remote Agent pairing and auth

Pairing flow:

1. Host creates a six-digit code with `POST /remote/pair/start` from loopback or another trusted context.
2. Client sends `POST /remote/pair/confirm` with code, device name, and platform.
3. Host returns a bearer token and device metadata.
4. Client stores the token in platform secret storage.
5. Protected `/remote/*` requests use `Authorization: Bearer <token>`.

Token operations:

- `POST /remote/tokens/refresh`: rotate/refresh the current device token.
- `GET /remote/devices`: list registered devices.
- `DELETE /remote/devices/{id}`: revoke a device.
- `DELETE /remote/devices/revoked`: purge revoked devices.

Client rules:

- Preserve local token/cache on transient network failures.
- On 401/403, enter `authRejected`; do not silently clear token.
- Local token deletion only removes the client copy. Host-side revocation is a separate user action.

## 3. Public HTTPS direct path

Default topology:

```text
Android/macOS client
  → https://211-216-28-65.sslip.io
  → router WAN TCP 443
  → Windows Host TCP 38443
  → Caddy sidecar
  → http://127.0.0.1:8000 Remote Agent
```

User-facing input policy:

- Android and macOS ask for **공유기 WAN 공인 IPv4** only.
- `211.216.28.65` becomes `https://211-216-28-65.sslip.io` internally.
- The generated host URL is not shown as a primary editable field.

Router rule:

| Purpose | Protocol | External | Internal target | Internal |
| --- | --- | ---: | --- | ---: |
| HomeworkHelper control plane | TCP | 443 | Windows Host | 38443 |

`Remote Agent 8000` stays bound behind Caddy/reverse proxy and must not be forwarded directly.

## 4. Shared status states

Stable states:

| State | User meaning | Required behavior |
| --- | --- | --- |
| `online` | Remote Agent and auth are usable | Enable supported commands and sync payloads |
| `offlineExpected` | Host/network is likely unavailable | Show cached game state and offline guidance |
| `agentUnavailable` | HTTPS route exists but Agent/HTTP is unavailable | Show cached state and server/port guidance |
| `authRejected` | Stored token is rejected | Preserve cache/token, show pairing recovery |

Transient states:

| State | Meaning |
| --- | --- |
| `unknown` | Initial state before enough evidence |
| `reconnecting` | Unexpected connection loss; short confirmation probes may run |
| `waking` | Client accepted a wake intent and expects host recovery |
| `goingOffline` | Host accepted sleep/shutdown and disconnect is expected |
| `restarting` | Host accepted restart and recovery is expected |

## 5. Evidence layers

1. **HTTP Agent**: `GET /remote/status` tells whether Remote Agent, auth, and host runtime are usable.
2. **Auth result**: HTTP 401/403 always maps to `authRejected`.
3. **Public HTTPS readiness**: `GET /remote/access/status` explains DNS/TLS/Caddy/router state.
4. **Local cache**: cached process snapshot keeps Home useful while disconnected.
5. **Power intent overlay**: accepted wake/sleep/restart/shutdown temporarily changes UI state.

Rules:

- Entering `online` from a non-online state forces one payload sync even if `state_revision` is unchanged.
- During `goingOffline`, a stale HTTP success must not immediately flip back to `online` unless the server reports a clear online power hint.
- `authRejected` clears reconnect schedules and waits for user action.

## 6. Remote payload synchronization

Required online payloads for the game mirror:

- `/remote/status`
- `/remote/readiness`
- `/remote/processes`

Optional payloads:

- dashboard summary
- Beholder incidents
- game links/mobile sessions
- device list
- logging config
- power status/setup
- remote access status

Cache rule: process snapshots are the minimum cache required for a good native client.

## 7. Power control boundary

Wake and disconnecting power actions intentionally have different paths:

- **Wake는 SmartThings**: the client uses SmartThings to turn on the configured `PC 켜기` device. This works even when the host HTTP server is offline.
- **Host HTTPS 위임**: `sleep`, `restart`, and `shutdown` are sent to the authenticated Remote Agent as `POST /remote/power/actions/{action}` only when `GET /remote/power/status` advertises support.

Host endpoints:

- `GET /remote/power/status`: current host-delegated power readiness and supported actions.
- `GET /remote/power/setup`: read-only setup/readiness information for diagnostics.
- `POST /remote/power/actions/{sleep|restart|shutdown}`: host accepts a supported local Windows power action and returns before the connection drops.

Invalid for active clients:

- Arbitrary command execution payloads.
- Exposing `Remote Agent 8000` directly to the internet.
- Wake over SSH or router broadcast forwarding.

## 8. Platform adapter boundaries

macOS adapters:

- Keychain token store.
- UserDefaults settings.
- Application Support process/icon cache.
- SmartThings wake.
- Host HTTPS delegated disconnecting power actions.
- Optional legacy Tailscale diagnostics may remain isolated from the primary direct path.

Android adapters:

- Android Keystore token/secret store.
- Preferences settings.
- Process/icon cache.
- Friendly network error classification.
- Public IPv4 to `https://<ip-with-dashes>.sslip.io` URL normalization.
- SmartThings REST wake.
- Host HTTPS delegated disconnecting power actions.

Shared principle: adapters perform side effects; reducer/state logic consumes typed results.

## 9. Verification expectations

Every client must prove:

- Auth failures enter recovery without deleting cache.
- Offline/agent-unavailable states preserve the last successful game snapshot.
- Launch actions are disabled when auth/offline/loading/running makes them unsafe.
- Power buttons are disabled unless their exact adapter is configured and supported.
- Public IP setup explains **TCP 443 → Windows Host 38443** and keeps `Remote Agent 8000` private.
