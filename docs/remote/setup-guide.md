# HomeworkHelper Remote Client Setup Guide

Last refreshed: 2026-06-05

HomeworkHelper exposes a local **Remote Agent** from the Windows host app and controls it from the macOS menu-bar client. The current contract is host-owned data + token-protected remote endpoints + client-local power/Moonlight orchestration. Do not treat old roadmap, migration, spike, or preview-GUI notes as active remote requirements.

## 1. Remote Agent

Local development:

```bash
./.venv/bin/python homework_helper.pyw --server
```

Trusted private-network access:

```bash
HH_API_HOST=0.0.0.0 \
HH_API_PORT=8000 \
HH_REMOTE_REQUIRE_AUTH=1 \
./.venv/bin/python homework_helper.pyw --server
```

`--server` starts the FastAPI Remote Agent without entering the GUI single-instance/admin prompt path. SSH real-device test sessions can use `tools/ssh_host_testbench.py`; it shadow-copies the installed package, assigns an isolated port/mutex/AppData root, writes a local report under `artifacts/ssh-host-testbench/`, and cleans the remote temp root after the run.

Security rules:

- Never expose the Remote Agent without bearer-token auth.
- Prefer private LAN/tailnet routing or an explicitly authenticated reverse proxy over unauthenticated public forwarding.
- First-time VPN/system-extension/account approval remains an explicit user/admin action.
- `/remote/pair/start` is intended for loopback or trusted setup paths.
- The host does not expose arbitrary shell execution endpoints.
- If TCP is reachable but Remote Agent HTTP hangs or the Windows host app becomes sluggish, preserve the current state before restarting and follow `docs/remote/host-ssh-diagnostics-runbook.md`.
- For package-environment logic checks, prefer the isolated SSH testbench in `docs/remote/host-ssh-diagnostics-runbook.md` over probing or killing the production host process.

## 2. Pairing and token storage

1. Create a six-digit pairing code on the host:

```bash
curl -X POST http://127.0.0.1:8000/remote/pair/start
```

2. Enter Remote Agent URL, device name, and pairing code in the client.
3. Client calls `POST /remote/pair/confirm` and stores the returned device token.
4. Protected `/remote/*` endpoints use `Authorization: Bearer <token>`.
5. macOS keeps the returned device token stable until explicit device revoke via `/remote/devices*`.

Token storage requirements:

- macOS secret token: Keychain.
- Plain preferences: URL, device name, UI settings, cached non-secret host metadata only.
- Smoke tests must inject temporary token/preference/cache roots and must not mutate production user state.

## 3. Shared Remote API surface

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
- `GET /remote/power/status`, `GET /remote/power/setup`, `POST /remote/power/ssh-key`

Payload synchronization rules:

- Host data remains authoritative for process/game/link/session state.
- Client caches are disposable acceleration state, not a source of truth.
- Auth failures must return the client to a clearly repairable pairing/auth state.

## 4. macOS client UX and supervisor contract

Source: `clients/macos`

```bash
swift build --package-path clients/macos
./.venv/bin/python tools/package_macos_remote_app.py
open dist/macos/HomeworkHelperRemote.app
```

Primary UX contract:

- Menu-bar popover is the normal control surface.
- Settings opens only through explicit settings actions or the app shortcut.
- Pairing state, host reachability, Remote Agent auth, game/process state, and Moonlight desktop-session state must update the popover immediately enough for user decisions.
- Moonlight state is client-observed as well as app-command-observed; a visible Moonlight desktop session should be reflected even if it was launched externally.

Supervisor state contract:

- Connection state distinguishes host unreachable, Remote Agent unavailable, auth rejected, paired/ready, and degraded evidence.
- Evidence layers include HTTP readiness, pairing/auth response, cached host metadata, and client-local reachability signals.
- Client resume should request an immediate probe rather than waiting for the next slow poll.
- Recovery with unchanged revision should not duplicate cached processes or sessions.

Power boundary:

- The host reports readiness and can register SSH public keys.
- Wake/sleep/restart/shutdown are client-local side effects.
- Clients without a direct local power adapter must keep power buttons disabled.
- OpenSSH automation accepts explicit success markers from the selected command path only; absence of that marker is a failed power action even when the shell exits ambiguously.

Connection-state scenarios that must remain covered by tests/smokes:

- External host shutdown / hibernate
- Tailscale reachable but HTTP server down
- Auth rejected
- Client wake command accepted
- Recovery with unchanged revision
- Mac sleep then resume

## 5. Verification

Remote route/static checks:

```bash
./.venv/bin/python -m pytest tests/test_remote_routes.py
./.venv/bin/python -m pytest tests/test_remote_macos_client_static.py
swift build --package-path clients/macos
./.venv/bin/python tools/smoke_macos_remote_viewmodel.py
```

Stateful client smoke isolation contract:

- Client smokes must isolate local persistence from production user state.
- macOS ViewModel smoke must set `HH_REMOTE_CACHE_DIR`, `HH_REMOTE_PREFS_SUITE`, injected token store, and temporary power paths.
- Smoke fixtures may not write to production cache paths such as `~/Library/Application Support/HomeworkHelperRemote/cache/processes.json`.
- Tests that intentionally verify cache behavior must assert the production cache signature is unchanged.
- `tools/smoke_macos_connection_supervisor.py` validates the macOS supervisor state reducer.
