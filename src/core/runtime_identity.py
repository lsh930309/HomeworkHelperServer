"""Read the immutable build identity embedded in packaged host artifacts."""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import sys
from typing import Any


def _manifest_candidates() -> tuple[Path, ...]:
    candidates: list[Path] = []
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        candidates.append(Path(bundle_root) / "runtime-manifest.json")
    candidates.append(Path(sys.executable).resolve().parent / "runtime-manifest.json")
    candidates.append(Path(__file__).resolve().parents[2] / "build" / "runtime-manifest.json")
    return tuple(dict.fromkeys(candidates))


@lru_cache(maxsize=1)
def runtime_identity() -> dict[str, Any]:
    for path in _manifest_candidates():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if isinstance(payload, dict):
            return {
                "release_id": str(payload.get("release_id") or "unknown"),
                "git_sha": str(payload.get("git_hash") or payload.get("git_sha") or "unknown"),
                "manifest_path": str(path),
            }
    return {"release_id": "unknown", "git_sha": "unknown", "manifest_path": None}
