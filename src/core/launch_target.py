"""Registered launch target selection without database, GUI or OS side effects."""
from __future__ import annotations

import ntpath
import os.path
import re
from collections.abc import Mapping, Iterable
from typing import Any


def _value(process: Any, key: str, default=None):
    return process.get(key, default) if isinstance(process, Mapping) else getattr(process, key, default)


def launch_target_accepts_args(target: str | None) -> bool:
    if not target:
        return False
    value = str(target).strip()
    if value.lower().endswith((".lnk", ".url")):
        return False
    return not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", value) or bool(re.match(r"^[a-zA-Z]:", value))


def launcher_candidates(process: Any, launcher_patterns: Iterable[str]) -> tuple[str, ...]:
    """The caller observes file existence and passes that snapshot to resolution."""
    candidates = []
    for value in (_value(process, "launch_path"), _value(process, "monitoring_path")):
        if not value:
            continue
        paths = ntpath if re.match(r"^[a-zA-Z]:", str(value)) or "\\" in str(value) else os.path
        parent = paths.dirname(str(value))
        if parent:
            for pattern in launcher_patterns:
                candidate = paths.join(parent, str(pattern))
                if candidate not in candidates:
                    candidates.append(candidate)
    return tuple(candidates)


def resolve_launch_target(process: Any, mode: str | None = None, *, launcher_patterns: Iterable[str] = (), existing_paths: Iterable[str] = ()) -> tuple[str | None, str]:
    mode = mode or _value(process, "preferred_launch_type") or "shortcut"
    launch = _value(process, "launch_path")
    monitor = _value(process, "monitoring_path")
    if mode == "direct":
        return monitor or launch, mode
    if mode == "shortcut":
        return launch or monitor, mode
    if mode == "launcher":
        existing = set(existing_paths)
        target = next((item for item in launcher_candidates(process, launcher_patterns) if item in existing), None)
        return target or launch or monitor, mode
    return launch or monitor, "auto"


def resolve_launch_args(process: Any, mode: str, target: str | None) -> str | None:
    if mode == "launcher" or not launch_target_accepts_args(target) or not bool(_value(process, "launch_args_enabled", False)):
        return None
    return str(_value(process, "launch_args", "") or "").strip() or None
