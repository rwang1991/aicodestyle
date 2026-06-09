"""FastAPI app factory for the AIAnalyzer portal."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from aianalyzer import narrative as _narrative
from aianalyzer.web import services
from aianalyzer.web.jobs import REGISTRY

STATIC_DIR = Path(__file__).parent / "static"


class ScanRequest(BaseModel):
    pass  # reserved for future filters


def create_app() -> FastAPI:
    app = FastAPI(title="AIAnalyzer Portal", version="0.2.0")

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/scan", status_code=202)
    def start_scan(_: ScanRequest) -> dict[str, str]:
        job = REGISTRY.create(kind="scan")

        def _do(j):
            return services.run_scan(progress_cb=lambda p: setattr(j, "progress", p))

        REGISTRY.run(job, _do)
        return {"job_id": job.id}

    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: str) -> dict:
        j = REGISTRY.get(job_id)
        if j is None:
            raise HTTPException(404, detail="job not found")
        return {
            "id": j.id,
            "status": j.status,
            "progress": j.progress,
            "result": j.result,
            "error": j.error,
        }

    @app.get("/api/profile")
    def profile() -> dict:
        return services.load_profile_payload()

    @app.post("/api/narrative/start", status_code=202)
    def start_narrative() -> dict[str, str]:
        job = REGISTRY.create(kind="narrative")

        def _do(_j):
            facts = services.load_profile_payload()
            md = _narrative.generate_narrative(facts)
            return {"markdown": md}

        REGISTRY.run(job, _do)
        return {"job_id": job.id}

    return app
