"""Main GUI API facade.

This package exposes UI-oriented endpoints for the Tauri/React main window.
It must not own persistence directly; DB continuity stays in ``src.data``.
"""

from .routes import router

__all__ = ["router"]
