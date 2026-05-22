# macOS Remote Client Architecture

Last refreshed: 2026-05-19
Status: Active reference for native client rebuilds

## 1. Purpose

The macOS Remote Client is the reference native client for HomeworkHelper Remote. It is a menu-bar-first controller that mirrors the host's registered game state, lets the user launch host games, and keeps power/connectivity setup out of the main path until needed.

This document is the source of truth for rebuilding other native clients, especially Android. Platform-specific details may change, but the user jobs and Remote Agent contracts must stay aligned.

## 2. Primary UX contract

The main user surface is the menu-bar popover. It is intentionally not a large management dashboard.

Primary jobs:

1. Show registered games immediately.
2. Show per-game progress/status with clear visual feedback.
3. Launch a host game with one action.
4. Show host online/offline/auth state without hiding cached game state.
5. Keep setup, diagnostics, device management, and platform-specific integrations in settings.

Popover rules:

- Game rows are the primary content; setup controls are secondary.
- Row geometry is a contract: fixed icon lane, text lane, progress/status badge lane, and launch button lane.
- The main screen must remain useful while offline by showing cached processes and locally recomputed progress.
- Running state is shown through existing visual lanes rather than adding layout-shifting chrome.
- Settings can be richer, but the popover must stay fast, compact, and low-fatigue.

Android implication: the Android home screen should be the equivalent of the macOS popover, not a settings dashboard. Game state and launch affordances are the first screen; everything else supports that flow.

## 3. Code structure

Key files under `remote_clients/macos/HomeworkHelperRemote/Sources/HomeworkHelperRemote`:

- `HomeworkHelperRemoteApp.swift`: AppKit/SwiftUI shell, `NSStatusItem`, `NSPopover`, settings scene, popover rows, settings UI.
- `RemoteDashboardViewModel.swift`: main state machine, Remote Agent orchestration, cache sync, pairing flow, connectivity evaluation, local power setup commands.
- `RemoteAPIClient.swift`: low-level Remote Agent HTTP client and bearer-token boundary.
- `RemoteModels.swift`: snake_case API DTOs and local derived helpers.
- `RemoteClientCache.swift`: cached process snapshots and icon/resource-icon cache.
- `RemoteConnectionSupervisor.swift`: pure connectivity state reducer; no local side effects.
- `KeychainTokenStore.swift`: Keychain token persistence.
- `LocalPowerWakeManager.swift`: client-local SmartThings wake adapter.
- `LocalSSHPowerManager.swift`: client-local OpenSSH power adapter.
- `LocalSSHKeyManager.swift`: client-local keypair generation and public-key registration support.
- `TailscaleDiscovery.swift`: local Tailscale discovery, suggested URLs, and reachability helpers.

Boundary rule: `RemoteDashboardViewModel` owns side effects and delegates pure decisions to helpers. `RemoteConnectionSupervisor` must remain portable and deterministic.

## 4. Remote Agent API contract

The macOS client uses these shared `/remote/*` contracts:

- Pairing/token/device: `/remote/pair/confirm`, `/remote/tokens/refresh`, `/remote/devices`, `/remote/devices/{id}`, `/remote/devices/revoked`.
- Status/readiness: `/remote/status`, `/remote/capabilities`, `/remote/readiness`.
- Games/shortcuts: `/remote/processes`, `/remote/processes/{id}/launch`, `/remote/shortcuts`, `/remote/shortcuts/{id}/open`.
- Dashboard/alerts: `/remote/dashboard/summary`, `/remote/beholder/incidents`.
- Android/mobile data model: `/remote/game-links`, `/remote/mobile-sessions/active`, `/remote/mobile-sessions/start`, `/remote/mobile-sessions/end`.
- Diagnostics/connectivity setup: `/remote/logging/config`, `/remote/tailscale/ensure`.
- Power readiness only: `/remote/power/status`, `/remote/power/setup`, `/remote/power/ssh-key`.

Important power contract:

- The host does **not** expose `/remote/power/{action}` side-effect endpoints. The host does not expose `/remote/power/{action}` as an execution API.
- The host only reports setup/readiness and registers SSH public keys.
- Wake/sleep/restart/shutdown are client-local side effects.
- Any client that cannot implement a direct local power path must keep power action buttons disabled and explain why.

## 5. State and data flow

Startup/pairing:

1. Load base URL from `UserDefaults` and token from Keychain.
2. Probe status/readiness through `RemoteAPIClient`.
3. If no token, show pairing guidance.
4. On pairing, store token, register SSH public key if possible, refresh readiness and payloads.

Refresh/mirror:

1. `RemoteDashboardViewModel` calls `/remote/status` first.
2. `RemoteConnectionSupervisor` maps HTTP/auth/connectivity events to UI state.
3. If online and revision changed, sync dashboard, incidents, links, sessions, power setup, processes, devices when needed.
4. Save process snapshots and icons to cache.
5. If offline or agent unavailable, keep cached process cards visible and recompute local progress.

Main launch:

1. User presses a game launch button.
2. Client calls `POST /remote/processes/{id}/launch`.
3. Client keeps the host connection pill stable and marks only that game row as launch-pending.
4. Client runs an immediate process-scoped mirror plus a short launch chase window; it does not call the global refresh path solely because launch was accepted.
5. Failures are shown as user-visible messages; cached game state is not cleared on transient failures.

## 6. Connectivity supervisor contract

The supervisor reduces typed events into these states:

- Stable: `online`, `offlineExpected`, `agentUnavailable`, `authRejected`.
- Transient: `unknown`, `reconnecting`, `waking`, `goingOffline`, `restarting`.

It never runs Tailscale, SSH, HTTP, or platform APIs directly. The ViewModel provides evidence such as:

- HTTP status success/failure/auth failure.
- Management reachability result.
- Client power intent accepted.
- Client resume/wake event.

Recovery rule:

- When returning to `online` from any non-online state, force one payload sync even if `state_revision` did not change.
- Refresh SSH health on online recovery when SSH power is configured.

## 7. Local power system

Wake path:

- Client-local SmartThings CLI finds/selects a wake-capable PC device.
- Wake action never requires the host HTTP server to be online.

Sleep/restart/shutdown path:

- Client-local OpenSSH connects to the Windows host.
- SSH command emits an explicit accepted marker before or after the Windows command depending on action semantics.
- The UI treats the command as accepted only when the marker is observed.
- Accepted sleep/shutdown transitions to `goingOffline`; restart transitions to `restarting`.

SSH setup path:

- Client generates or reuses a local private key.
- Host `/remote/power/ssh-key` registers the public key into the effective Windows authorized keys file.
- Admin Windows accounts may use `C:\ProgramData\ssh\administrators_authorized_keys` depending on `sshd_config`.
- SSH health must authenticate with the intended key; accidental agent/key fallback is avoided with `IdentitiesOnly=yes`.

## 8. Persistence boundaries

- Keychain: bearer token only.
- UserDefaults: base URL, device name, UI settings, power preferences, popover settings.
- Application Support cache: process snapshots and icons.
- Desktop log: only when explicitly enabled.
- Host remote-local store: device registry, remote-local host readiness metadata, public key registration target.

Do not store host bearer tokens in plaintext preferences. Do not store client private key paths on the host as executable configuration.

## 9. Verification contract

For macOS client changes, run the smallest relevant checks first:

```bash
./.venv/bin/python -m pytest tests/test_remote_macos_client_static.py -q
swift build --package-path remote_clients/macos/HomeworkHelperRemote
./.venv/bin/python tools/smoke_macos_remote_viewmodel.py
```

Add `tools/smoke_macos_connection_supervisor.py` when touching connectivity recovery or `RemoteConnectionSupervisor.swift`.

Smoke caveat: `tools/smoke_macos_remote_viewmodel.py` compiles an explicit Swift source list. Any new production Swift helper required by `RemoteDashboardViewModel` must be added there or the smoke compile will fail.

## 10. Android rebuild guidance

Android should preserve the macOS client's product shape, not its AppKit mechanics:

- macOS popover -> Android home screen.
- Game row -> Android game card/list item.
- Menu-bar status icon -> top status banner/chip.
- Settings window -> secondary settings/setup screens.
- Keychain -> Android Keystore.
- UserDefaults -> SharedPreferences/DataStore-equivalent.
- `RemoteConnectionSupervisor` state model -> shared reducer concept with Android reachability adapters.
