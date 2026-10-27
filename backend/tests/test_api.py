"""API smoke tests (no runs executed): health, repos, graph gate, validation."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

SAMPLE = Path(__file__).resolve().parents[2] / "examples" / "sample_repo"


def _zip_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for path in SAMPLE.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                zf.write(path, str(path.relative_to(SAMPLE)))
    return buffer.getvalue()


def test_health():
    with TestClient(app) as client:
        data = client.get("/api/health").json()
        assert data["status"] == "ok"
        assert data["llm_mode"] in {"mock", "openai"}
        assert data["isolation"] in {"docker", "local"}


def test_upload_and_graph_gate():
    with TestClient(app) as client:
        resp = client.post("/api/repos/upload",
                           files={"file": ("sample_repo.zip", _zip_bytes(), "application/zip")})
        assert resp.status_code == 201, resp.text
        repo_id = resp.json()["id"]
        assert resp.json()["file_count"] > 5

        detail = client.get(f"/api/repos/{repo_id}").json()
        assert detail["tree"]["type"] == "dir"
        assert client.get(f"/api/repos/{repo_id}/file",
                          params={"path": "orders/service.py"}).status_code == 200
        assert client.get(f"/api/repos/{repo_id}/file",
                          params={"path": "../etc/passwd"}).status_code == 404

        # B/C require a built graph -> 400
        resp = client.post("/api/runs", json={
            "repo_id": repo_id, "task": "quantity validation fix", "systems": ["B"]})
        assert resp.status_code == 400
        assert "graph" in resp.json()["detail"].lower()

        # unknown repo -> 404
        assert client.post("/api/runs", json={
            "repo_id": "r_nope", "task": "x", "systems": ["A"]}).status_code == 400

        # benchmark catalog
        tasks = client.get("/api/benchmark/tasks").json()
        assert any(t["id"] == "bugfix-single-item-validation" for t in tasks)
        results = client.get("/api/benchmark/results").json()
        assert set(results["aggregates"]) == {"A", "B", "C"}
