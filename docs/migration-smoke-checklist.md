# Migration Smoke Checklist

Windows-only manual smoke cannot be completed on the current macOS device and is not a completion gate for the current goal. Keep the entries so parity can be verified on a Windows machine later.

## Main GUI table sizing with real data

- [x] Extract `HomeworkHelper.zip` to a temporary clone only; do not mutate the ZIP or the user's real AppData.
- [x] Load cloned `homework_helper_data/app_data.db` through model objects/API-shaped test doubles.
- [x] Launch the PyQt main GUI with screenshot, recording, sidebar, tray, and toast side effects disabled.
- [x] Capture `artifacts/gui-screenshots/main-realdata.png`.
- [x] Confirm horizontal headers and vertical row numbers are hidden.
- [x] Confirm game names are sorted alphabetically by displayed name.
- [x] Confirm game names, progress widgets, launch buttons, and status labels are visible without text clipping in the captured image.
- [x] Confirm pathological long names do not force the window beyond the available screen width; table overflow scrolling is enabled instead.

## Sidebar drawer handle

- [x] Confirm the active sidebar trigger starts with the handle always visible and not transparent-for-input.
- [x] Confirm handle CSS uses `border: none` and the sidebar frame is borderless.
- [x] Confirm clicking the handle invokes the sidebar controller's `slide_in()` path without hiding the handle.
- [x] Confirm polling can restore the handle without depending on cursor hover position.
- [ ] Windows: with sidebar enabled and a game running, confirm the handle is already visible at the configured screen edge.
- [ ] Windows: click the handle and confirm the sidebar opens; let it auto-hide after the configured delay.
