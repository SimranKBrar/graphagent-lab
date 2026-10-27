"""Repository endpoints: upload, GitHub connect, metadata, files."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, UploadFile

from .. import db
from ..repo import ingest
from ..schemas import GitHubRepoRequest

router = APIRouter(prefix="/api", tags=["repos"])

MAX_UPLOAD_BYTES = 200 * 1024 * 1024


@router.get("/repos")
def list_repos():
    return [ingest.repo_summary(r) for r in ingest.list_repos()]


@router.post("/repos/upload", status_code=201)
async def upload_repo(file: UploadFile):
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(400, detail="Only .zip archives are supported")
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, detail="Archive exceeds the 200 MB limit")
    try:
        return ingest.ingest_zip(data, file.filename or "repo.zip")
    except ingest.IngestError as exc:
        raise HTTPException(400, detail=str(exc)) from exc


@router.post("/repos/github", status_code=201)
def add_github_repo(payload: GitHubRepoRequest):
    try:
        return ingest.ingest_github(payload.url, payload.branch)
    except ingest.IngestError as exc:
        message = str(exc)
        status = 502 if "clone" in message else 400
        raise HTTPException(status, detail=message) from exc


@router.get("/repos/{repo_id}")
def get_repo(repo_id: str):
    repo = ingest.get_repo(repo_id)
    if repo is None:
        raise HTTPException(404, detail="repository not found")
    local = repo["local_path"]
    from pathlib import Path
    tree = ingest.build_tree(Path(local)) if Path(local).exists() else None
    return {**repo, "tree": tree}


@router.get("/repos/{repo_id}/file")
def get_file(repo_id: str, path: str):
    repo = ingest.get_repo(repo_id)
    if repo is None:
        raise HTTPException(404, detail="repository not found")
    try:
        return ingest.read_file(repo, path)
    except FileNotFoundError as exc:
        raise HTTPException(404, detail=f"file not found: {path}") from exc


@router.delete("/repos/{repo_id}")
def delete_repo(repo_id: str):
    if not ingest.delete_repo(repo_id):
        raise HTTPException(404, detail="repository not found")
    return {"ok": True}
