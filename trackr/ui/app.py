"""FastAPI app: JSON API + static HTML/JS pages for the trackr UI."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .. import store

STATIC_DIR = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    app = FastAPI(title="trackr")
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/api/runs")
    def api_list_runs(project: Optional[str] = None):
        conn = store.connect()
        try:
            runs = store.list_runs(conn, project=project)
            for r in runs:
                r["config"] = json.loads(r["config"])
                r["final_metrics"] = store.get_final_metrics(conn, r["id"])
            return runs
        finally:
            conn.close()

    @app.get("/api/runs/{run_id}")
    def api_get_run(run_id: str):
        conn = store.connect()
        try:
            r = store.get_run(conn, run_id)
            if r is None:
                raise HTTPException(status_code=404, detail="run not found")
            r["config"] = json.loads(r["config"])
            r["final_metrics"] = store.get_final_metrics(conn, run_id)
            return r
        finally:
            conn.close()

    @app.get("/api/runs/{run_id}/metrics")
    def api_get_metrics(run_id: str):
        conn = store.connect()
        try:
            return store.get_metrics(conn, run_id)
        finally:
            conn.close()

    @app.get("/api/runs/{run_id}/artifacts")
    def api_get_artifacts(run_id: str):
        conn = store.connect()
        try:
            return store.get_artifacts(conn, run_id)
        finally:
            conn.close()

    @app.get("/api/artifacts/{run_id}/{filename}")
    def api_get_artifact_file(run_id: str, filename: str):
        artifacts_dir = (store.get_artifacts_dir() / run_id).resolve()
        path = (artifacts_dir / filename).resolve()
        if artifacts_dir not in path.parents or not path.exists():
            raise HTTPException(status_code=404, detail="artifact not found")
        return FileResponse(str(path))

    @app.get("/", response_class=HTMLResponse)
    def index():
        return (STATIC_DIR / "index.html").read_text()

    @app.get("/run/{run_id}", response_class=HTMLResponse)
    def run_detail(run_id: str):
        return (STATIC_DIR / "run.html").read_text()

    return app
