# macOS Remote Client Architecture

Last refreshed: 2026-06-04
Status: Active reference for native client rebuilds

## 1. Purpose

The macOS Remote Client is the reference native client for HomeworkHelper Remote. It is a menu-bar-first controller that mirrors the host's registered game state, launches host games, and keeps setup/diagnostics out of the main path until needed.

The current connectivity baseline is **공개 HTTPS 직접접속**. The user enters only the **공유기 WAN 공인 IPv4**; the client internally derives `https://<ip-with-dashes>.sslip.io`.

## 2. Primary UX contract

Primary jobs:

1. Show registered games immediately.
2. Show per-game progress/status with clear visual feedback.
3. Launch a host game with one action.
4. Show host online/offline/auth state without hiding cached game state.
5. Keep setup, diagnostics, device management, and platform integrations in settings.

Settings contract:

- Primary host field: **공유기 공인 IP**.
- No primary editable Host URL field.
- The public HTTPS URL may be used internally for requests and diagnostics but should not be the main UX object.
- Wake remains SmartThings based.
- Sleep/restart/shutdown use **Host HTTPS 위임** when advertised by `/remote/power/status`.

## 3. Code structure

Key files under `remote_clients/macos/HomeworkHelperRemote/Sources/HomeworkHelperRemote`:

- `HomeworkHelperRemoteApp.swift`: AppKit/SwiftUI shell, popover rows, settings UI.
- `RemoteDashboardViewModel.swift`: state machine, Remote Agent orchestration, cache sync, pairing, connectivity, SmartThings wake, delegated power.
- `RemoteAPIClient.swift`: low-level Remote Agent HTTP client and bearer-token boundary.
- `RemoteModels.swift`: snake_case API DTOs and derived helpers.
- `RemoteClientCache.swift`: cached process snapshots and icon/resource-icon cache.
- `RemoteConnectionSupervisor.swift`: pure connectivity state reducer.
- `KeychainTokenStore.swift`: Keychain token persistence.
- `LocalPowerWakeManager.swift`: SmartThings wake adapter.
- `TailscaleDiscovery.swift`: legacy/optional local diagnostics only; not the primary connection path.

Boundary rule: `RemoteDashboardViewModel` owns side effects and delegates pure decisions to helpers. `RemoteConnectionSupervisor` remains portable and deterministic.

## 4. Remote Agent API contract

The macOS client uses these shared `/remote/*` contracts:

- Pairing/token/device: `/remote/pair/confirm`, `/remote/tokens/refresh`, `/remote/devices`, `/remote/devices/{id}`, `/remote/devices/revoked`.
- Status/readiness: `/remote/status`, `/remote/capabilities`, `/remote/readiness`.
- Games/shortcuts: `/remote/processes`, `/remote/processes/{id}/launch`, `/remote/shortcuts`, `/remote/shortcuts/{id}/open`.
- Dashboard/alerts: `/remote/dashboard/summary`, `/remote/beholder/incidents`.
- Android/mobile data model: `/remote/game-links`, `/remote/mobile-sessions/active`, `/remote/mobile-sessions/start`, `/remote/mobile-sessions/end`.
- Diagnostics/connectivity setup: `/remote/logging/config`, `/remote/access/status`.
- Power: `/remote/power/status`, `/remote/power/setup`, `/remote/power/actions/{sleep|restart|shutdown}`.

Important power contract:

- **Wake는 SmartThings** and does not require host HTTP availability.
- **Host HTTPS 위임** handles sleep/restart/shutdown after the host reports support.
- Unsupported actions are disabled and explained.

## 5. Public HTTPS data flow

Startup/pairing:

1. Load the saved public IPv4-derived URL and token.
2. If the stored value is invalid or private, leave the host input blank and ask for the router public IPv4.
3. Probe `/remote/status` and `/remote/readiness` through `RemoteAPIClient`.
4. Pair with `POST /remote/pair/confirm` and store the token in Keychain.
5. Refresh `/remote/access/status` so the user can see Caddy/router readiness.

Network path:

```text
macOS client
  → https://<공인IP-대시>.sslip.io
  → 공유기 WAN TCP 443
  → Windows Host TCP 38443
  → Caddy
  → Remote Agent 8000 on loopback
```

Router rule: **TCP 443 → Windows Host 38443**. Do not forward `Remote Agent 8000` directly.

## 6. Connectivity supervisor contract

The supervisor reduces typed events into these states:

- Stable: `online`, `offlineExpected`, `agentUnavailable`, `authRejected`.
- Transient: `unknown`, `reconnecting`, `waking`, `goingOffline`, `restarting`.

It never runs platform APIs directly. The ViewModel provides HTTP status, public HTTPS readiness, cache state, and power-intent events.

Recovery rule:

- Returning to `online` from any non-online state forces one payload sync even if `state_revision` did not change.
- Accepted sleep/shutdown transitions to `goingOffline`; accepted restart transitions to `restarting`.

## 7. Persistence boundaries

- Keychain: bearer token only.
- UserDefaults: derived base URL, router public IP display value, device name, UI settings, SmartThings preferences.
- Application Support cache: process snapshots and icons.
- Host remote-local store: device registry, public HTTPS/Caddy readiness metadata.

Do not store bearer tokens in plaintext preferences. Do not store client private keys as host-executable configuration.

## 8. Verification contract

For macOS client changes, run the smallest relevant checks first:

```bash
./.venv/bin/python -m pytest tests/test_remote_macos_client_static.py -q
swift build --package-path remote_clients/macos/HomeworkHelperRemote
./.venv/bin/python tools/smoke_macos_remote_viewmodel.py
```

Add `tools/smoke_macos_connection_supervisor.py` when touching connectivity recovery or `RemoteConnectionSupervisor.swift`.

## 9. Android rebuild guidance

Android should preserve the macOS product shape, not AppKit mechanics:

- macOS popover → Android home screen.
- Game row → Android game card/list item.
- Settings window → Android Setup tab.
- Keychain → Android Keystore.
- UserDefaults → SharedPreferences/DataStore-equivalent.
- SmartThings wake and Host HTTPS delegated power remain aligned across clients.
