"""Repository ingestion: zip upload, GitHub clone, metadata scan, file tree."""
from __future__ import annotations

import io
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Any, Optional

from .. import db, config

IGNORED_DIRS = {".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
                "dist", "build", ".next", ".cache", ".pytest_cache", ".mypy_cache", "target"}
MAX_ZIP_BYTES = 200 * 1024 * 1024
MAX_FILES = 20000
TREE_DEPTH_LIMIT = 12

LANG_BY_EXT = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript", ".ts": "TypeScript",
    ".tsx": "TypeScript", ".java": "Java", ".go": "Go", ".rs": "Rust", ".rb": "Ruby",
    ".php": "PHP", ".c": "C", ".h": "C", ".cpp": "C++", ".hpp": "C++", ".cs": "C#",
    ".swift": "Swift", ".kt": "Kotlin", ".scala": "Scala", ".sh": "Shell",
    ".html": "HTML", ".css": "CSS", ".sql": "SQL", ".md": "Markdown", ".json": "JSON",
    ".yaml": "YAML", ".yml": "YAML", ".toml": "TOML",
}


class IngestError(ValueError):
    pass


def _new_id(prefix: str) -> str:
    import uuid
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _is_ignored(name: str) -> bool:
    return name in IGNORED_DIRS or name.startswith(".")


def scan_repo(path: Path) -> dict[str, Any]:
    """Walk the repository and collect counts, sizes, and language histogram."""
    file_count = 0
    total_bytes = 0
    languages: dict[str, int] = {}
    for root, dirs, files in path.walk():
        rel_root = root.relative_to(path)
        dirs[:] = sorted(d for d in dirs if not _is_ignored(d))
        if len(rel_root.parts) > TREE_DEPTH_LIMIT:
            dirs[:] = []
            continue
        for fname in sorted(files):
            file_count += 1
            if file_count > MAX_FILES:
                break
            fpath = root / fname
            try:
                size = fpath.stat().st_size
            except OSError:
                size = 0
            total_bytes += size
            lang = LANG_BY_EXT.get(Path(fname).suffix.lower())
            if lang is None:
                lang = "Other"
            languages[lang] = languages.get(lang, 0) + 1
    return {
        "file_count": file_count,
        "total_bytes": total_bytes,
        "languages": dict(sorted(languages.items(), key=lambda kv: -kv[1])),
    }


def build_tree(path: Path) -> dict[str, Any]:
    """Directory/file tree (JSON-safe), excluding ignored dirs, depth-limited."""

    def build(current: Path, depth: int) -> dict[str, Any]:
        entries: list[dict[str, Any]] = []
        try:
            children = sorted(current.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except OSError:
            children = []
        for child in children:
            if _is_ignored(child.name):
                continue
            rel = str(child.relative_to(path))
            if child.is_dir():
                if depth + 1 > TREE_DEPTH_LIMIT:
                    continue
                node = build(child, depth + 1)
                # Collapse single-child directories to keep the tree compact.
                while (len(node["children"]) == 1 and node["children"][0]["type"] == "dir"):
                    only = node["children"][0]
                    node = {"name": f"{node['name']}/{only['name']}",
                            "path": only["path"], "type": "dir", "children": only["children"]}
                if node["children"]:
                    entries.append(node)
            else:
                try:
                    size = child.stat().st_size
                except OSError:
                    size = 0
                entries.append({"name": child.name, "path": rel, "type": "file", "bytes": size})
        return {"name": current.name if depth else path.name,
                "path": "" if depth == 0 else str(current.relative_to(path)),
                "type": "dir", "children": entries}

    return build(path, 0)


def _git(path: Path, *args: str, timeout: int = 300) -> str:
    proc = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True,
                          timeout=timeout)
    if proc.returncode != 0:
        raise IngestError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return proc.stdout.strip()


def _finalize(repo_id: str, name: str, source_type: str, local_path: Path,
              origin_url: Optional[str], branch: Optional[str]) -> dict[str, Any]:
    stats = scan_repo(local_path)
    commit = None
    if (local_path / ".git").exists():
        try:
            commit = _git(local_path, "rev-parse", "HEAD")
            if branch is None:
                branch = _git(local_path, "rev-parse", "--abbrev-ref", "HEAD")
        except (IngestError, subprocess.TimeoutExpired):
            commit = None
    created = db.utcnow()
    db.execute(
        "INSERT INTO repositories (id, name, source_type, origin_url, local_path, "
        "default_branch, commit_sha, file_count, total_bytes, languages, graph_status, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,'absent',?)",
        (repo_id, name, source_type, origin_url, str(local_path), branch, commit,
         stats["file_count"], stats["total_bytes"], json_dumps(stats["languages"]), created),
    )
    return get_repo(repo_id)  # type: ignore[return-value]


def json_dumps(obj: Any) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False)


def ingest_zip(data: bytes, filename: str) -> dict[str, Any]:
    if len(data) > MAX_ZIP_BYTES:
        raise IngestError("Archive too large (max 200 MB)")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise IngestError(f"Invalid zip archive: {exc}") from exc
    with zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
        if not names:
            raise IngestError("Archive is empty")
        if len(names) > MAX_FILES:
            raise IngestError("Archive contains too many files")
        repo_id = _new_id("r")
        dest = config.REPOS_DIR / repo_id
        dest.mkdir(parents=True, exist_ok=True)
        # If every entry shares one top-level directory, strip it.
        tops = {n.split("/")[0] for n in zf.namelist() if n.strip("/")}
        strip = next(iter(tops)) if len(tops) == 1 and all("/" in n for n in zf.namelist() if not n.endswith("/")) else None
        for member in names:
            target_name = member[len(strip) + 1:] if strip and member.startswith(strip + "/") else member
            if not target_name:
                continue
            target = (dest / target_name).resolve()
            if not str(target).startswith(str(dest.resolve())):
                raise IngestError("Archive contains unsafe paths")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
    name = Path(filename or "repo.zip").stem or "uploaded-repo"
    return _finalize(repo_id, name, "zip", dest, None, None)


GITHUB_URL_RE = re.compile(r"^https://github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")


def ingest_github(url: str, branch: Optional[str] = None) -> dict[str, Any]:
    match = GITHUB_URL_RE.match(url.strip())
    if not match:
        raise IngestError("Only https://github.com/owner/repo URLs are supported")
    owner, repo_name = match.group(1), match.group(2)
    repo_id = _new_id("r")
    dest = config.REPOS_DIR / repo_id
    cmd = ["git", "clone", "--depth", "1"]
    if branch:
        cmd += ["--branch", branch]
    cmd += [url.strip(), str(dest)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired as exc:
        raise IngestError("git clone timed out") from exc
    if proc.returncode != 0:
        shutil.rmtree(dest, ignore_errors=True)
        raise IngestError(f"git clone failed: {(proc.stderr or '').strip()[:400]}")
    return _finalize(repo_id, repo_name, "github", dest, url.strip(), branch)


def get_repo(repo_id: str) -> Optional[dict[str, Any]]:
    row = db.query_one("SELECT * FROM repositories WHERE id = ?", (repo_id,))
    if row is None:
        return None
    data = db.row_to_dict(row, json_fields=("languages",))
    if data is not None and "commit_sha" in data:
        data["commit"] = data.pop("commit_sha")   # 'commit' is a SQLite keyword
    return data


def list_repos() -> list[dict[str, Any]]:
    rows = db.query("SELECT * FROM repositories ORDER BY created_at DESC")
    out = []
    for row in rows:
        data = db.row_to_dict(row, json_fields=("languages",))
        if data is not None:
            data["commit"] = data.pop("commit_sha", None)
            out.append(data)
    return out


def repo_summary(repo: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": repo["id"], "name": repo["name"], "source_type": repo["source_type"],
        "origin_url": repo["origin_url"], "created_at": repo["created_at"],
        "default_branch": repo["default_branch"], "file_count": repo["file_count"],
        "languages": repo["languages"], "graph_status": repo["graph_status"],
    }


def delete_repo(repo_id: str) -> bool:
    repo = get_repo(repo_id)
    if repo is None:
        return False
    db.execute("DELETE FROM repositories WHERE id = ?", (repo_id,))
    runs = db.query("SELECT id FROM runs WHERE repo_id = ?", (repo_id,))
    for run in runs:
        delete_run(run["id"])
    path = Path(repo["local_path"])
    if path.exists() and str(path.resolve()).startswith(str(config.REPOS_DIR.resolve())):
        shutil.rmtree(path, ignore_errors=True)
    graph_file = config.GRAPHS_DIR / f"{repo_id}.json"
    if graph_file.exists():
        graph_file.unlink()
    return True


def delete_run(run_id: str) -> None:
    db.execute("DELETE FROM events WHERE run_id = ?", (run_id,))
    db.execute("DELETE FROM run_systems WHERE run_id = ?", (run_id,))
    db.execute("DELETE FROM runs WHERE id = ?", (run_id,))


def read_file(repo: dict[str, Any], rel_path: str, max_bytes: int = 200 * 1024) -> dict[str, Any]:
    base = Path(repo["local_path"]).resolve()
    target = (base / rel_path).resolve()
    if not str(target).startswith(str(base)) or not target.is_file():
        raise FileNotFoundError(rel_path)
    raw = target.read_bytes()[:max_bytes]
    return {"path": rel_path, "content": raw.decode("utf-8", errors="replace"),
            "truncated": len(raw) >= max_bytes}
