"""Shared runtime URL/port helpers for the local API server."""

from __future__ import annotations

import os


DEFAULT_API_PORT = 8000
LOCAL_API_HOST = "127.0.0.1"


def resolve_api_port(default: int = DEFAULT_API_PORT) -> int:
    """Return the configured API port, falling back to the stable default."""
    raw_port = os.environ.get("HH_API_PORT")
    if not raw_port:
        return default
    try:
        port = int(raw_port)
    except ValueError:
        return default
    return port if 0 < port < 65536 else default


def resolve_local_api_base_url(base_url: str | None = None) -> str:
    """Return the loopback URL GUI clients should use for the local API."""
    if base_url:
        return str(base_url).rstrip("/")
    return f"http://{LOCAL_API_HOST}:{resolve_api_port()}"


def dashboard_url(base_url: str | None = None) -> str:
    """Return the dashboard entry URL for a local API base URL."""
    return f"{resolve_local_api_base_url(base_url)}/dashboard"


def gui_health_url(base_url: str | None = None) -> str:
    """Return the GUI/backend readiness endpoint URL for a local API base URL."""
    return f"{resolve_local_api_base_url(base_url)}/api/gui/health"
