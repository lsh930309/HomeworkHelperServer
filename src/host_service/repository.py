"""Read the existing user's canonical DB without importing its writer or ORM."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace


@dataclass(frozen=True)
class SettingsSnapshot:
    run_as_admin: bool
    run_on_startup: bool
    obs_exe_path: str = ""
    obs_launch_hidden: bool = True


@dataclass(frozen=True)
class UserSnapshot:
    settings: SettingsSnapshot
    processes: tuple[SimpleNamespace, ...]

    def process(self, process_id: str) -> SimpleNamespace:
        for process in self.processes:
            if process.id == process_id:
                return process
        raise LookupError("등록된 실행 대상을 찾을 수 없습니다.")


class ReadOnlyUserRepository:
    """One transaction snapshots only settings and managed targets. Never creates DBs."""

    def read(self, session, *, settings_only=False) -> UserSnapshot:
        database = Path(session.appdata_dir) / "homework_helper_data" / "app_data.db"
        # A URI in mode=ro fails if absent, even if a caller races the existence check.
        connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            settings = connection.execute(
                "SELECT run_as_admin, run_on_startup, obs_exe_path, obs_launch_hidden FROM global_settings WHERE id = 1"
            ).fetchone()
            if settings is None:
                raise LookupError("기존 사용자 설정을 찾을 수 없습니다.")
            if settings_only:
                return UserSnapshot(SettingsSnapshot(bool(settings["run_as_admin"]),
                                                     bool(settings["run_on_startup"]), settings["obs_exe_path"] or "",
                                                     bool(settings["obs_launch_hidden"])), ())
            # Do not read cookie, pairing, incident or session tables in the service.
            rows = connection.execute(
                "SELECT id, name, monitoring_path, launch_path, original_launch_path, "
                "preferred_launch_type, launch_args_enabled, launch_args, user_preset_id "
                "FROM managed_processes"
            ).fetchall()
            processes = tuple(SimpleNamespace(**dict(row)) for row in rows)
            return UserSnapshot(
                SettingsSnapshot(bool(settings["run_as_admin"]), bool(settings["run_on_startup"]), settings["obs_exe_path"] or "",
                                                     bool(settings["obs_launch_hidden"])),
                processes,
            )
        finally:
            connection.close()


def preset_launch_inputs(process, session) -> tuple[tuple[str, ...], frozenset[str]]:
    """Read packaged preset patterns and snapshot candidate existence for pure resolution."""
    if not getattr(process, "user_preset_id", None):
        return (), frozenset()
    import sys
    from src.core.launch_target import launcher_candidates

    user_file = Path(session.appdata_dir) / "game_presets_user.json"
    bundle = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    for preset_file in (user_file, bundle / "src" / "data" / "game_presets.json"):
        if not preset_file.is_file():
            continue
        with preset_file.open(encoding="utf-8-sig") as stream:
            presets = json.load(stream)
        preset = next((item for item in presets.get("presets", [])
                       if item.get("id") == process.user_preset_id), None)
        if preset:
            patterns = tuple(preset.get("launcher_patterns", ()))
            existing = frozenset(candidate for candidate in launcher_candidates(process, patterns) if Path(candidate).is_file())
            return patterns, existing
    return (), frozenset()
