"""FastAPI application: API routes, health, CORS, optional built-frontend mount."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import config, db
from .api import benchmark, graphs, repos, runs
from .repo import workspace as ws

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    config.ensure_dirs()
    db.connect()
    yield


app = FastAPI(title="GraphAgent Lab", version="0.1.0",
              description="Multi-agent coding benchmark and graph intelligence platform",
              lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS or ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(repos.router)
app.include_router(graphs.router)
app.include_router(runs.router)
app.include_router(benchmark.router)


@app.get("/api/health")
def health():
    # Reported from configuration (no client instantiation / no network calls).
    mode = config.LLM_MODE
    return {
        "status": "ok",
        "version": "0.1.0",
        "llm_mode": mode,
        "model": config.OPENAI_MODEL if mode == "openai" else "mock-scripted",
        "isolation": ws.preview_isolation(),
        "docker_available": ws.docker_available(),
    }


# Serve the production frontend build when present (frontend/dist).
_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="frontend")
