"""Pydantic request/response models for the HTTP API."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

SystemID = Literal["A", "B", "C"]


class GitHubRepoRequest(BaseModel):
    url: str
    branch: Optional[str] = None


class RunSettings(BaseModel):
    max_iterations: Optional[int] = Field(None, ge=1, le=10)
    tool_call_budget: Optional[int] = Field(None, ge=5, le=500)
    token_budget: Optional[int] = Field(None, ge=1000, le=500_000)
    timeout_sec: Optional[int] = Field(None, ge=30, le=3600)
    model: Optional[str] = None


class RunCreate(BaseModel):
    repo_id: str
    task: str = Field(min_length=1, max_length=8000)
    systems: list[SystemID] = Field(default_factory=lambda: ["A", "B", "C"], min_length=1)
    settings: RunSettings = Field(default_factory=RunSettings)


class EventOut(BaseModel):
    seq: int
    ts: str
    system: Optional[str]
    type: str
    stage: Optional[str]
    agent: Optional[str]
    payload: dict[str, Any]
