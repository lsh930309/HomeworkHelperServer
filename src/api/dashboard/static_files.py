"""Dashboard static bundle path resolution."""

from __future__ import annotations

import sys
from pathlib import Path

from src.utils.common import get_base_path, get_bundle_resource_path


DASHBOARD_STATIC_BUILD_DIR = Path("build") / "dashboard-static"
DASHBOARD_PACKAGED_STATIC_DIR = Path("src") / "api" / "dashboard" / "static"


def dashboard_static_dir() -> Path:
    """Return the directory mounted at /static/dashboard.

    Development runs serve Vite output from the ignored build directory so source
    files never receive generated bundles. PyInstaller runs serve the same files
    after the spec maps that build output into the bundle's source-shaped data
    path.
    """
    if getattr(sys, "frozen", False) or getattr(sys, "_MEIPASS", None):
        return Path(get_bundle_resource_path(str(DASHBOARD_PACKAGED_STATIC_DIR)))
    return Path(get_base_path()) / DASHBOARD_STATIC_BUILD_DIR
