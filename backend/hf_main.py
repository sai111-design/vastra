"""Hugging Face Spaces entrypoint — one process, one port for SPA + API.

On HF Spaces the React build and the FastAPI backend are served together on a
single port. This module reuses the exact app from :func:`backend.main.create_app`
(so the API, lifespan, CORS, and checkpointer are identical to local dev) and
additionally mounts the built frontend at ``/`` with an SPA catch-all.

The static mount is added LAST so it never shadows the ``/api`` routers: Starlette
matches explicit routes before the ``/`` mount. ``html=True`` makes ``StaticFiles``
serve ``index.html`` for unknown client-side routes (deep links / refresh).

The frontend build (``frontend/dist``) does not exist until Stage 7, so the
mount is guarded — until then this entrypoint serves the API alone.

Run with: ``uvicorn backend.hf_main:app --host 0.0.0.0 --port 8000``.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi.staticfiles import StaticFiles

from backend.main import create_app

logger = logging.getLogger(__name__)

app = create_app()

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
_FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"

_MOUNT_DIR = _STATIC_DIR if _STATIC_DIR.is_dir() else _FRONTEND_DIST

if _MOUNT_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(_MOUNT_DIR), html=True), name="spa")
    logger.info("Mounted SPA from %s", _MOUNT_DIR)
else:
    logger.warning(
        "Frontend build not found at %s or %s — serving API only (Stage 7 builds the SPA)",
        _STATIC_DIR,
        _FRONTEND_DIST,
    )
