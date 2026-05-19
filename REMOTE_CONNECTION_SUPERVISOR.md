# Remote Connection Supervisor, Pairing, and Power Protocol

Last refreshed: 2026-05-19
Status: Shared protocol reference for macOS and Android clients

## 1. Purpose

This document defines the shared Remote Client connectivity protocol. It is not a macOS-only implementation note. Platform clients may use different reachability probes or power adapters, but they must present the same connection semantics to users.

The supervisor is a reducer: it accepts typed evidence and returns UI state, reconnect schedule guidance, and payload-sync hints. It must not directly perform HTTP, Tailscale, SSH, SmartThings, Android, or AppKit side effects.

## 2. Remote Agent pairing and auth

Pairing flow:

1. Host creates a six-digit code with `POST /remote/pair/start` from loopback or an already trusted context.
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

## 3. Shared status states

Stable states:

| State | User meaning | Required behavior |
| --- | --- | --- |
| `online` | Remote Agent and auth are usable | Enable supported commands and sync payloads |
| `offlineExpected` | Host/network is likely unavailable | Show cached game state and offline guidance |
| `agentUnavailable` | Host may be reachable but Remote Agent/HTTP is unavailable | Show cached state and server/port guidance |
| `authRejected` | Stored token is rejected | Preserve cache/token, show pairing/token recovery guidance |

Transient states:

| State | Meaning |
| --- | --- |
| `unknown` | Initial state before enough evidence |
| `reconnecting` | Unexpected connection loss; short confirmation probes may run |
| `waking` | Client accepted a wake intent and expects host recovery |
| `goingOffline` | Client accepted sleep/shutdown and expects disconnect |
| `restarting` | Client accepted restart and expects disconnect then recovery |

## 4. Evidence layers

All clients should evaluate evidence in this order where available:

1. **HTTP Agent**: `GET /remote/status` tells whether Remote Agent, auth, and host runtime are usable.
2. **Auth result**: HTTP 401/403 always maps to `authRejected`.
3. **Management reachability**: optional platform-specific evidence that host/network exists even if HTTP failed.
   - macOS may use Tailscale ping and SSH health.
   - Android v1 may initially skip this and rely on friendly HTTP error categories.
4. **Local cache**: cached process snapshot keeps the main UI useful while disconnected.
5. **Client power intent overlay**: accepted local power commands temporarily override ambiguous HTTP results.

HTTP failure interpretation:

- Timeout/no route/DNS failure plus management no-reply -> `offlineExpected`.
- Connection refused/HTTP port unavailable with management reachable or inconclusive -> `agentUnavailable`.
- Unknown failures should prefer preserving cache and showing actionable copy over clearing state.

## 5. Supervisor reducer contract

Inputs should be typed events, for example:

- `httpStatusSucceeded(powerHint, stateRevision)`
- `httpStatusFailed(kind, message)`
- `authRejected`
- `powerIntentAccepted(action)`
- `clientResumed`

Outputs should include:

- availability state
- user-facing message, if any
- reconnect schedule, if any
- whether to force payload sync
- whether to load/cache local snapshot
- whether to clear pairing-recovery message

Rules:

- Entering `online` from any non-online state forces one payload sync even if `state_revision` is unchanged.
- During `goingOffline`, a stale HTTP success must not immediately flip back to `online` unless the server reports a clear online/non-offline power hint.
- `authRejected` clears reconnect schedules and waits for user action.
- The supervisor never parses raw SSH stdout/stderr. Platform adapters convert local command output into accepted/failed events.

## 6. Remote payload synchronization

Required online payloads for the main game mirror:

- `/remote/status`
- `/remote/readiness`
- `/remote/processes`

Optional payloads:

- dashboard summary
- Beholder incidents
- game links/mobile sessions
- device list
- logging config
- power setup/status

Cache rule:

- Process snapshots are the minimum cache required for a good native client.
- If payload sync fails after status success, keep previous snapshot and show partial error/stale state.
- Last successful base URL and sync time should be visible in diagnostics or status copy.

## 7. Remote power control boundary

The host Remote Agent does not execute power actions. It reports readiness and registers SSH public keys only.

Host endpoints:

- `GET /remote/power/status`: report client-managed power status.
- `GET /remote/power/setup`: report host OpenSSH readiness and effective authorized-keys target.
- `POST /remote/power/ssh-key`: register a client public key for future client-local SSH control.

Invalid for current clients:

- `/remote/power/{action}` execution endpoints.
- Arbitrary command execution payloads.
- Host-stored client private key paths.

Client responsibilities:

- Wake: use a client-local wake adapter, currently SmartThings on macOS.
- Sleep/restart/shutdown: use client-local OpenSSH, currently implemented on macOS.
- Android: keep power actions disabled until Android-local direct adapters exist.

## 8. OpenSSH automation protocol

SSH setup:

1. Client creates or selects a local private key.
2. Client sends the public key to `POST /remote/power/ssh-key`.
3. Host writes the key to the effective Windows authorized keys target.
4. Client runs SSH health with the intended key only.

Windows authorized-key details:

- Normal users usually use `%USERPROFILE%\.ssh\authorized_keys`.
- Administrator accounts may use `C:\ProgramData\ssh\administrators_authorized_keys` when `sshd_config` has `Match Group administrators` with `AuthorizedKeysFile __PROGRAMDATA__/ssh/administrators_authorized_keys`.
- Host setup response must expose enough information for the client to explain which target was used.

SSH command acceptance:

- Commands must include an explicit marker such as `__HH_REMOTE_POWER_ACCEPTED__`.
- The client treats a power command as accepted only when the marker is observed.
- Missing marker, timeout, permission denied, no route, or command failure means not accepted.
- Accepted commands emit a supervisor `powerIntentAccepted(action)` event.

Current macOS command policy:

- `shutdown`: Windows `shutdown /s /t 0` plus marker.
- `restart`: Windows `shutdown /r /t 0` plus marker.
- `sleep`: marker is emitted before direct `rundll32.exe powrprof.dll,SetSuspendState 0,0,0`, because Windows OpenSSH may drop the session as sleep begins.
- `IdentitiesOnly=yes` prevents accidental success through unrelated SSH agent keys.

## 9. Platform adapter boundaries

macOS adapters:

- Keychain token store.
- UserDefaults settings.
- Application Support process/icon cache.
- Tailscale CLI discovery.
- SmartThings wake.
- OpenSSH power.

Android adapters to implement later:

- Android Keystore token store.
- Preferences/DataStore settings.
- Process/icon cache.
- Friendly network error classification.
- Optional package/Usage Access integration.
- Optional Android-local power adapters only if a safe direct path is designed.

Shared principle: adapters perform side effects; reducer/state logic consumes typed results.

## 10. Verification expectations

Every client must prove:

- Auth failures enter a recovery state without deleting cache.
- Offline/agent-unavailable states preserve last successful game snapshot.
- Launch actions are disabled when auth/offline/loading/running makes them unsafe.
- Power actions are disabled unless the platform has a direct, verified local power adapter.
- Payload sync after online recovery refreshes process state at least once.
