# Android Remote Client Rebuild Design

Last refreshed: 2026-06-04
Status: Active Android client implementation guide

## 1. Decision

Android is now a game-first public HTTPS direct client. The user enters only the **공유기 WAN 공인 IPv4**. The app internally derives `https://<ip-with-dashes>.sslip.io`, hides the generated URL from the primary UI, and uses the shared Remote Agent bearer-token contract.

The first supported external-network mode is **공개 HTTPS 직접접속** with **수동 포트포워딩**. Automatic router mapping is deferred. Android no longer owns client-side VPN or SSH automation for HomeworkHelper remote control.

## 2. Product goal

Primary job:

> Open the app, immediately see the host's registered games, then launch or stop the desired host game with clear feedback.

Secondary jobs:

- Pair this Android device with the host Remote Agent.
- Diagnose public HTTPS reachability, auth, and host readiness.
- Preserve cached game state while offline.
- Manage paired-device and token lifecycle tasks.
- Wake the PC through SmartThings.
- Delegate sleep/restart/shutdown to the host over authenticated HTTPS when the host reports support.

## 3. UX structure

Bottom navigation has two user-action surfaces:

1. **Home / Games**: default screen, game mirror, quick launch/stop, pull-to-refresh, status feedback.
2. **Setup**: public IP pairing, power readiness, paired devices, app diagnostics.

Setup input policy:

- The visible host field is **공유기 공인 IP** only.
- Accepted input is a public IPv4 literal such as `211.216.28.65`.
- The app stores `https://211-216-28-65.sslip.io` internally.
- URL, port, LAN/private, link-local, loopback, and CGNAT inputs are rejected in the normal UX.

## 4. Home screen blueprint

Home mirrors the macOS popover:

- Host status chip and last-sync copy.
- Registered game cards with host icons/resource icons.
- Running/today-played badges.
- `[실행]` for `POST /remote/processes/{id}/launch`.
- Red `[중단]` with confirmation for `POST /remote/processes/{id}/stop`.
- Pull-to-refresh and short command-chase refreshes after accepted launch/stop.
- Offline/auth errors preserve cached process cards.

## 5. Setup screen

Sections:

1. **연결/페어링**: 공유기 공인 IP, device name, pairing code, token status, Connection Doctor.
2. **전원**: SmartThings Wake readiness plus Host HTTPS delegated sleep/restart/shutdown readiness.
3. **기기 관리**: device list, revoke, cleanup.
4. **앱 동작**: diagnostics and fake Remote Agent smoke guidance.

Connection Doctor checks the internally generated URL for DNS/TLS/Bearer/Remote Agent readiness and explains the router rule:

```text
공유기 WAN TCP 443 → Windows Host TCP 38443 → Caddy → Remote Agent 8000
```

The user-facing setup copy must repeat that `Remote Agent 8000` is local-only and must not be forwarded directly.

## 6. Android implementation architecture

```text
app/src/main/java/dev/homeworkhelper/remote/
├── MainActivity.kt
├── data/RemoteApiClient.kt
├── data/RemoteModels.kt
├── data/RemoteRepository.kt
├── data/SmartThingsClient.kt
├── state/RemoteViewModel.kt
├── platform/TokenStore.kt
├── platform/Preferences.kt
├── platform/AutomationPreferences.kt
├── platform/PowerAction.kt
├── platform/RemoteNetworkController.kt
└── ui/
```

Rules:

- Keep HTTP free of Compose state.
- Keep token persistence behind platform secret storage.
- Treat cached process snapshots as a first-class Home requirement.
- Keep public-IP normalization in one policy boundary.
- Do not add a background network/VPN lifecycle controller.

## 7. Shared Remote Agent API subset

Required for Home:

- `GET /remote/status`
- `GET /remote/readiness`
- `GET /remote/processes`
- `POST /remote/processes/{id}/launch`
- `POST /remote/processes/{id}/stop`

Required for setup:

- `POST /remote/pair/confirm`
- `GET /remote/access/status`
- `GET /remote/devices`
- `DELETE /remote/devices/{id}`
- `DELETE /remote/devices/revoked`
- `GET /remote/power/status`
- `POST /remote/power/actions/{sleep|restart|shutdown}`

Power policy:

- **Wake는 SmartThings**: Android sends SmartThings REST commands to the configured `PC 켜기` device.
- **Host HTTPS 위임**: sleep/restart/shutdown call the host Remote Agent action endpoint only when `/remote/power/status` reports the action in `supported_actions`.
- Unsupported power actions remain disabled with an explanation.

## 8. Connectivity model

The primary path is **공개 HTTPS 직접접속**:

```text
Android client
  → https://<공인IP-대시>.sslip.io
  → 공유기 WAN TCP 443
  → Windows Host TCP 38443
  → Caddy sidecar
  → http://127.0.0.1:8000 Remote Agent
```

Router requirement: **TCP 443 → Windows Host 38443**. No UDP port is required for the HomeworkHelper control plane. Sunshine/Apollo/Moonlight media-plane ports remain separate.

Supervisor states:

- `online`: Remote Agent and auth are usable.
- `offlineExpected`: host/network likely unavailable.
- `agentUnavailable`: HTTPS path reached something, but Remote Agent/HTTP is unavailable.
- `authRejected`: bearer token rejected.
- transient `waking`, `goingOffline`, `restarting` for power intents.

## 9. Verification expectations

- Invalid host input rejects URLs, ports, LAN/private, loopback, link-local, and CGNAT.
- Public IPv4 input normalizes to `https://<ip-with-dashes>.sslip.io` internally.
- Launch/stop actions preserve cached cards on transient failure.
- SmartThings Wake works without host HTTP being online.
- Sleep/restart/shutdown use Host HTTPS delegated power and never expose `Remote Agent 8000` publicly.
