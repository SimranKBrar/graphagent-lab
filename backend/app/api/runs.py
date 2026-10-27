"""Run endpoints: create, list, detail, SSE event stream, cancel, system detail."""
from __future__ import annotations

import asyncio
import json
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from ..agents import runner, runstore
from ..schemas import RunCreate

router = APIRouter(prefix="/api", tags=["runs"])

POLL_INTERVAL = 0.35
HEARTBEAT_AFTER = 8.0


@router.post("/runs", status_code=201)
def create_run(payload: RunCreate):
    try:
        return runner.create_run(payload.repo_id, payload.task, list(payload.systems),
                                 payload.settings.model_dump(exclude_none=True))
    except runner.RunError as exc:
        raise HTTPException(400, detail=str(exc)) from exc


@router.get("/runs")
def list_runs():
    return [runstore.run_summary(r) for r in runstore.list_runs()]


@router.get("/runs/{run_id}")
def get_run(run_id: str):
    detail = runstore.run_detail(run_id)
    if detail is None:
        raise HTTPException(404, detail="run not found")
    return detail


@router.get("/runs/{run_id}/events")
def get_events(run_id: str, request: Request, after: int = 0,
               format: Optional[str] = None, limit: int = 500):
    if runstore.get_run(run_id) is None:
        raise HTTPException(404, detail="run not found")
    if format == "json":
        events = runstore.get_events(run_id, after=after, limit=min(limit, 2000))
        next_after = events[-1]["seq"] if events else after
        return {"events": events, "next_after": next_after}
    return StreamingResponse(_sse_stream(run_id, after, request),
                             media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no",
                                      "Connection": "keep-alive"})


async def _sse_stream(run_id: str, after: int, request: Request):
    cursor = int(after)
    idle_since = asyncio.get_running_loop().time()
    yield "retry: 1000\n\n"
    while True:
        if await request.is_disconnected():
            return
        events = await asyncio.to_thread(runstore.get_events, run_id, cursor, 500)
        if events:
            for event in events:
                cursor = event["seq"]
                yield f"event: msg\ndata: {json.dumps(event, default=str)}\n\n"
            idle_since = asyncio.get_running_loop().time()
        else:
            run = await asyncio.to_thread(runstore.get_run, run_id)
            if run is None:
                yield "event: end\ndata: {}\n\n"
                return
            if run.get("status") in {"completed", "failed", "cancelled"}:
                # One last synchronous drain to avoid missing trailing rows.
                trailing = await asyncio.to_thread(runstore.get_events, run_id, cursor, 500)
                if trailing:
                    for event in trailing:
                        cursor = event["seq"]
                        yield f"event: msg\ndata: {json.dumps(event, default=str)}\n\n"
                    continue
                yield "event: end\ndata: {}\n\n"
                return
            now = asyncio.get_running_loop().time()
            if now - idle_since > HEARTBEAT_AFTER:
                yield ": heartbeat\n\n"
                idle_since = now
        await asyncio.sleep(POLL_INTERVAL)


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str):
    if runstore.get_run(run_id) is None:
        raise HTTPException(404, detail="run not found")
    ok = runner.cancel_run(run_id)
    return {"ok": ok}


@router.get("/runs/{run_id}/system/{system}")
def get_system(run_id: str, system: str):
    if system not in {"A", "B", "C"}:
        raise HTTPException(400, detail="system must be A, B or C")
    detail = runstore.system_detail(run_id, system)
    if detail is None:
        raise HTTPException(404, detail="run or system not found")
    return detail
