# Remote Storage Policy

The remote feature uses a hybrid storage model.

## DB-backed data

Keep user intent and product policy in the main HomeworkHelper database:

- global settings, including remote server mode
- managed process definitions
- web shortcuts
- play/mobile session records
- mobile/game-link metadata

These records are part of the normal application domain and should continue to flow through the existing CRUD/API paths.

## Local `%AppData%` data

Keep machine-local remote integration state outside the DB under:

```text
%APPDATA%/HomeworkHelper/remote/
```

This includes:

- paired remote device tokens and revocation state (`remote_devices.json`)
- remote desktop logging preference (`remote_debug_logging.json`)
- remote-local audit/diagnostic append-only files

These files contain machine-specific credentials, paths, tokens, or host integration details. They should not be migrated into the shared DB.

## Preservation contract

`src/core/remote_local_store.py` owns all remote-local files. Callers should not write these files directly.

The store guarantees:

1. legacy migration from the previous flat `%APPDATA%/HomeworkHelper/*.json` location;
2. atomic write via same-directory temporary file + replace;
3. rotating backups under `%APPDATA%/HomeworkHelper/remote/backups/`;
4. a SHA-256 manifest at `%APPDATA%/HomeworkHelper/remote/manifest.json`;
5. a `/remote/local-store/health` readiness endpoint for integrity checks.

Future changes that add remote-local settings must route through `RemoteLocalStore` so pairing and power configuration do not evaporate after package updates.
