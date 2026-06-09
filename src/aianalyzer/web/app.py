"""FastAPI app factory for the AIAnalyzer portal."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    app = FastAPI(title="AIAnalyzer Portal", version="0.2.0")

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
