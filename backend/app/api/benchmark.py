"""Benchmark endpoints: task catalog and aggregated results."""
from __future__ import annotations

from fastapi import APIRouter

from ..benchmark import metrics as metrics_mod
from ..benchmark import tasks as tasks_mod

router = APIRouter(prefix="/api/benchmark", tags=["benchmark"])


@router.get("/tasks")
def task_catalog():
    return tasks_mod.catalog()


@router.get("/results")
def results():
    return metrics_mod.aggregate()
