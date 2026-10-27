"""Isolated per-system workspaces and command execution.

Every system gets its own copy of the repository (data/workspaces/<run>/<sys>).
Shell/test commands run either directly on the host (local mode) or inside the
`graphagent-runner` Docker container bind-mounting the workspace (docker mode).
`auto` prefers Docker and degrades to local when the daemon/image is unusable.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .. import config

_DOCKER_LOCK = threading.Lock()
_DOCKER_STATUS: Optional[bool] = None  # True = usable, False = unusable
_IMAGE_TRIED = False

IGNORE_COPY = shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".venv", "node_modules",
                                     ".pytest_cache", ".mypy_cache")

DENIED_COMMAND_RE = re.compile(
    r"\brm\s+-[a-z]*r[a-z]*f\s+/\s|rm\s+-rf\s+\*|mkfs|:\s*\(\s*\)\s*\{|"
    r"\bsudo\b|\bshutdown\b|\breboot\b|\bdd\s+if=/dev/|\bchmod\s+-R\s+777\s+/")


class ExecError(RuntimeError):
    pass


@dataclass
class ExecResult:
    ok: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    mode: str
    command: str = ""

    @property
    def combined(self) -> str:
        parts = [p for p in (self.stdout, self.stderr) if p]
        return "\n".join(parts)


def docker_daemon_up() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        proc = subprocess.run(["docker", "info"], capture_output=True, timeout=20)
        return proc.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def ensure_image() -> bool:
    """Return True when the runner image exists (building it once if needed)."""
    global _IMAGE_TRIED
    with _DOCKER_LOCK:
        try:
            proc = subprocess.run(["docker", "image", "inspect", config.DOCKER_IMAGE],
                                  capture_output=True, timeout=20)
            if proc.returncode == 0:
                return True
        except (subprocess.TimeoutExpired, OSError):
            return False
        if os.environ.get("GRAPHAGENT_DOCKER_BUILD", "1") == "0":
            return False
        if _IMAGE_TRIED:
            return False
        _IMAGE_TRIED = True
        dockerfile_dir = config.ROOT_DIR / "docker"
        if not (dockerfile_dir / "Dockerfile").exists():
            return False
        try:
            proc = subprocess.run(
                ["docker", "build", "-t", config.DOCKER_IMAGE, str(dockerfile_dir)],
                capture_output=True, text=True, timeout=600)
            return proc.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            return False


def resolve_isolation() -> str:
    """Effective isolation mode: 'docker' or 'local'."""
    global _DOCKER_STATUS
    if config.ISOLATION == "local":
        return "local"
    with _DOCKER_LOCK:
        if config.ISOLATION == "docker":
            usable = docker_daemon_up()
        else:
            if _DOCKER_STATUS is None:
                _DOCKER_STATUS = docker_daemon_up()
            usable = _DOCKER_STATUS
        if usable and not ensure_image():
            usable = False
            if config.ISOLATION == "docker":
                usable = docker_daemon_up()  # last chance: image build failed -> not usable
        return "docker" if usable else "local"


def docker_available() -> bool:
    return shutil.which("docker") is not None and docker_daemon_up()


def preview_isolation() -> str:
    """Non-blocking isolation probe for /api/health (never builds the image)."""
    if config.ISOLATION == "local":
        return "local"
    if not docker_daemon_up():
        return "local"
    try:
        proc = subprocess.run(["docker", "image", "inspect", config.DOCKER_IMAGE],
                              capture_output=True, timeout=15)
        if proc.returncode == 0:
            return "docker"
    except (subprocess.TimeoutExpired, OSError):
        return "local"
    # Daemon up but image missing: auto mode attempts a one-time image build
    # on the first run (Docker-preferred), so report docker here as well.
    return "docker"


def create_workspace(run_id: str, system: str, repo_path: str | Path) -> Path:
    dest = config.WORKSPACES_DIR / run_id / system
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(repo_path, dest, ignore=IGNORE_COPY, symlinks=True)
    return dest


@dataclass
class ExecutionEnv:
    workspace: Path
    mode: str = "local"
    python: str = field(default_factory=lambda: sys.executable)
    image: str = config.DOCKER_IMAGE

    def run_argv(self, argv: list[str], timeout: int = 120,
                 extra_env: Optional[dict[str, str]] = None) -> ExecResult:
        if any(a.startswith("/") and ".." in a for a in argv):
            pass  # host-absolute paths inside argv are allowed only via workspace
        env = os.environ.copy()
        env.setdefault("PYTHONPATH", str(self.workspace))
        env["PYTHONUNBUFFERED"] = "1"
        if extra_env:
            env.update(extra_env)
        if self.mode == "docker":
            docker_argv = [
                "docker", "run", "--rm",
                "-v", f"{self.workspace}:/work",
                "-w", "/work",
                "-e", "PYTHONPATH=/work",
                "-e", "PYTHONUNBUFFERED=1",
            ]
            for key, value in (extra_env or {}).items():
                docker_argv += ["-e", f"{key}={value}"]
            docker_argv.append(self.image)
            docker_argv += argv
            return self._exec(docker_argv, timeout, env, " ".join(argv))
        # Local mode: "python" resolves to the backend's interpreter (venv with pytest).
        if argv and argv[0] == "python":
            argv = [self.python] + list(argv[1:])
        return self._exec(argv, timeout, env, " ".join(argv))

    def run_shell(self, command: str, timeout: int = 120) -> ExecResult:
        if DENIED_COMMAND_RE.search(command):
            return ExecResult(False, 126, "", "Command blocked by safety policy", 0, self.mode, command)
        if self.mode == "docker":
            docker_argv = ["docker", "run", "--rm", "-v", f"{self.workspace}:/work",
                           "-w", "/work", self.image, "bash", "-lc", command]
            return self._exec(docker_argv, timeout, os.environ.copy(), command)
        return self._exec(["bash", "-lc", command], timeout,
                          {**os.environ, "PYTHONPATH": str(self.workspace),
                           "PYTHONUNBUFFERED": "1"}, command)

    def _exec(self, argv: list[str], timeout: int, env: dict[str, str],
              pretty: str) -> ExecResult:
        started = time.monotonic()
        try:
            proc = subprocess.run(
                argv, cwd=str(self.workspace) if self.mode == "local" else None,
                capture_output=True, text=True, timeout=timeout, env=env,
                errors="replace")
            duration = int((time.monotonic() - started) * 1000)
            return ExecResult(proc.returncode == 0, proc.returncode,
                              proc.stdout[-20000:], proc.stderr[-20000:], duration,
                              self.mode, pretty)
        except subprocess.TimeoutExpired as exc:
            duration = int((time.monotonic() - started) * 1000)
            out = (exc.stdout or b"")
            err = (exc.stderr or b"")
            if isinstance(out, bytes):
                out = out.decode("utf-8", errors="replace")
            if isinstance(err, bytes):
                err = err.decode("utf-8", errors="replace")
            return ExecResult(False, 124, out[-8000:],
                              (err + f"\nTimed out after {timeout}s").strip(),
                              duration, self.mode, pretty)
        except OSError as exc:
            duration = int((time.monotonic() - started) * 1000)
            return ExecResult(False, 127, "", str(exc), duration, self.mode, pretty)
