# Project Verification Contract

This repository is migrating from the PyQt GUI to a packaged Tauri/React preview GUI while preserving the existing `%APPDATA%/HomeworkHelper/homework_helper_data/app_data.db` contract.

## Always-on migration safety

- Before implementing or reviewing changes that touch GUI behavior, API routes, data models, DB writes, settings, packaging, launcher/runtime behavior, Beholder, screenshots, OBS, HoYoLab, sidebar, sessions, dashboard, or notifications, consult:
  - `docs/migration-feature-inventory.md`
  - `tests/migration/feature_matrix.json`
  - `docs/migration-smoke-checklist.md`
- When adding, removing, or changing a user-visible feature, update the feature matrix and inventory in the same change.
- When touching a high-risk data feature, add or update an automated test unless the behavior is Windows-only; for Windows-only behavior, add/update the smoke checklist entry.
- Do not introduce UI/router direct DB commits. Writes must go through CRUD/API boundaries and Beholder where applicable.
- The default installed GUI remains `homework_helper.exe`/PyQt until the migration matrix has no high-risk `new_gui_status=missing` blockers. `homework_helper_gui.exe` is a packaged preview shell.

## Required verification habit

For ordinary code changes, run the strongest feasible automated gate before completion:

```bash
python tools/verify_project.py
```

For packaging or Tauri shell changes, run the full gate:

```bash
python tools/verify_project.py --full
```

If any part cannot run in the current environment, report the exact skipped command and why, then run the next-best narrower checks. Windows-only behavior must be verified against `docs/migration-smoke-checklist.md` before declaring migration parity.
