# GraphAgent Lab — Internal API Contract (v1)

Base URL: `http://localhost:8000`  ·  All routes prefixed `/api`.
All timestamps are ISO-8601 UTC strings. All JSON responses are UTF-8.

## Core enums

```
SystemID    = "A" | "B" | "C"        # A=Standard, B=Graph-Augmented, C=GNN-Enhanced
Stage       = "explore" | "plan" | "edit" | "test" | "repair" | "done"
RunStatus   = "queued" | "running" | "completed" | "failed" | "cancelled"
SysStatus   = "pending" | "running" | "completed" | "failed" | "cancelled"
GraphStatus = "absent" | "building" | "ready" | "error"
```

## Health

### `GET /api/health`
```json
{
  "status": "ok",
  "version": "0.1.0",
  "llm_mode": "mock",            // "mock" | "openai"
  "model": "gpt-4o-mini",
  "isolation": "docker",         // "docker" | "local"  (effective mode)
  "docker_available": true
}
```

## Repositories

### `GET /api/repos` → `RepoSummary[]`
```json
{ "id": "r_ab12cd", "name": "orders-service", "source_type": "zip|github",
  "origin_url": null, "created_at": "...", "default_branch": null,
  "file_count": 42, "languages": {"Python": 30, "Other": 12},
  "graph_status": "ready" }
```

### `POST /api/repos/upload` — multipart field `file` (a .zip) → `Repo`
### `POST /api/repos/github` — JSON `{ "url": "https://github.com/org/repo", "branch": "main"? }` → `Repo`
Errors: 400 invalid archive/url, 409 duplicate, 502 clone failure.

### `GET /api/repos/{id}` → `RepoDetail`
```json
{
  "id": "r_ab12cd", "name": "...", "source_type": "zip", "origin_url": null,
  "created_at": "...", "default_branch": null, "commit": "abc123|null",
  "file_count": 42, "total_bytes": 123456, "languages": {"Python": 30},
  "graph_status": "ready",
  "tree": { "name": "root", "path": "", "type": "dir",
            "children": [ {"name": "app.py", "path": "app.py", "type": "file", "bytes": 1200} ] }
}
```
`tree` collapses directories containing only a single child into chain-free flat dirs; hidden dirs (`.git`) and `node_modules` are excluded. Depth limit 12.

### `GET /api/repos/{id}/file?path=app/core.py` → `{ "path": "...", "content": "...", "truncated": false }`
404 if missing. Content capped at 200 KB.

### `DELETE /api/repos/{id}` → `{ "ok": true }` (also removes its workspaces/graphs)

## Code knowledge graph

### `GET /api/repos/{id}/graph` →
```json
{ "status": "ready", "stats": { "nodes": 120, "edges": 300,
    "by_kind": {"function": 80, "class": 20, "module": 15, "test_function": 5},
    "by_edge": {"calls": 150, "imports": 60, "inherits": 10, "defines": 95, "tests": 20},
    "built_at": "..." }, "error": null }
```

### `POST /api/repos/{id}/graph` → `{ "status": "building" }` — starts background build (thread). Poll `GET`.

### `GET /api/repos/{id}/graph/data` → node-link data
```json
{
  "nodes": [
    { "id": "app/core.py::create_order", "label": "create_order", "kind": "function",
      "file": "app/core.py", "line": 12, "test": false, "loc": 30,
      "gnn_score": 0.83, "gnn_impact": 0.41 }
  ],
  "edges": [
    { "id": "e0", "source": "app/core.py::create_order",
      "target": "app/core.py::validate_order", "type": "calls" }
  ]
}
```
`gnn_score` / `gnn_impact` are `null` until a GNN model exists (Phase 3); the graph explorer hides badges for `null`.
Layout is computed client-side (React Flow) — backend does not send positions.

### `GET /api/repos/{id}/graph/search?q=order` → node summaries (max 50)

### `GET /api/repos/{id}/graph/node?node_id=<urlencoded id>` →
```json
{ "node": { ...as above... },
  "source": "def create_order(...)\n...",
  "callers": [ {"id": "...", "label": "..."} ],
  "callees": [ ... ],
  "related": [ {"id": "...", "type": "imports|inherits|tests"} ] }
```
`source` is the file slice for the node (functions/classes), whole file for modules; `null` if unavailable.

### `GET /api/repos/{id}/graph/subgraph?center=<node_id>&depth=2` → same shape as `/data`

## Runs

### `POST /api/runs`
```json
{ "repo_id": "r_ab12cd",
  "task": "Fix the validation bug in create_order so negative quantities are rejected.",
  "systems": ["A", "B", "C"],
  "settings": {                  // all optional, defaults shown
    "max_iterations": 3,         // repair cycles
    "tool_call_budget": 60,      // per system
    "token_budget": 60000,       // per system (prompt+completion)
    "timeout_sec": 600,          // per system
    "model": null                // override; null = server default
  } }
```
→ `201 { "id": "run_...", ...RunDetail }`  ·  Starts execution immediately.
400 if graph-dependent systems (B/C) requested and graph not `ready` (message tells user to build graph first).

### `GET /api/runs` → `RunSummary[]` (newest first, max 100)
```json
{ "id": "run_...", "repo_id": "r_ab12cd", "repo_name": "orders-service",
  "task": "...", "systems": ["A","B","C"], "status": "running",
  "created_at": "...", "finished_at": null }
```

### `GET /api/runs/{id}` → `RunDetail`
```json
{ ...RunSummary,
  "settings": { ... },
  "systems": [
    { "system": "A", "status": "running", "stage": "test", "current_agent": "test",
      "started_at": "...", "finished_at": null, "error": null,
      "metrics": { "tool_calls": 12, "llm_calls": 8, "tokens": 4210,
                   "cost_usd": 0.0063, "files_inspected": 5, "files_modified": 1,
                   "graph_queries": 0, "tests_passed": 4, "tests_failed": 1,
                   "repairs": 0, "duration_ms": 18300, "completion": "partial" },
      "plan": null, "test_report": null }   // plan/test_report appear once produced
  ] }
```
`completion`: `"pending" | "success" | "partial" | "failed"`.

### `GET /api/runs/{id}/events?after=0` → SSE (`text/event-stream`)
Server polls the event log; emits `event: msg\ndata: <Event>\n\n` for each new event.
Stream ends with `event: end` when run reaches a terminal status.
Reconnect is supported via `after=<last seq>` (EventSource: `?after` must be set at open time; frontend re-opens with last seen seq).

### `GET /api/runs/{id}/events?after=0&format=json&limit=500` → `{ "events": Event[], "next_after": 42 }`

**Event**
```json
{ "seq": 17, "ts": "...", "system": "B", "type": "tool_call",
  "stage": "explore", "agent": "explore", "payload": { ... } }
```

Event types → payloads:

| type | payload |
|---|---|
| `run_started` | `{task, systems}` |
| `system_started` | `{isolation: "docker"\|"local"}` |
| `stage_started` | `{stage}` |
| `stage_finished` | `{stage, ok: true}` |
| `llm_call` | `{agent, model, mock, prompt_tokens, completion_tokens, total_tokens, duration_ms}` |
| `tool_call` | `{agent, tool, args, call_id}` |
| `tool_result` | `{agent, tool, call_id, ok, duration_ms, preview}` (preview ≤ 800 chars) |
| `graph_visit` | `{agent, node_ids: [...], reason}` — nodes an agent touched (for explorer replay) |
| `explore_report` | `{findings: [{file, note}], symbols: [...], files_inspected: [...]}` |
| `plan_generated` | `{steps: [{id, description, files, symbols}]}` |
| `edit_applied` | `{path, action: "create"\|"modify"\|"delete", additions, deletions}` |
| `test_results` | `{passed, failed, failures: [{name, error, file, line}]}` |
| `repair_attempt` | `{diagnosis, root_cause, target_stage}` |
| `metric_update` | full `metrics` object (emitted after every meaningful step) |
| `stage_transition` | `{from, to, reason}` (orchestrator decision) |
| `budget_exceeded` | `{budget: "tokens"\|"tools"\|"iterations"\|"time"}` |
| `system_finished` | `{status, completion, duration_ms}` |
| `run_finished` | `{status}` |
| `log` | `{level: "info"\|"warn"\|"error", message}` |
| `error` | `{message, stage?}` |

### `POST /api/runs/{id}/cancel` → `{ "ok": true }`

### `GET /api/runs/{id}/system/{sys}` → per-system deep detail
```json
{ "system": "B", "status": "...", "stage": "...", "metrics": {...},
  "explore_report": {...}|null, "plan": {...}|null,
  "edits": [ {"path": "app/core.py", "action": "modify", "diff": "--- a/...", "additions": 4, "deletions": 2} ],
  "test_report": {...}|null,
  "repairs": [ {"diagnosis": "...", "root_cause": "...", "target_stage": "edit"} ],
  "workspace": "data/workspaces/<run>/<sys>" }
```

## Benchmark (Phase 4 scaffold)

### `GET /api/benchmark/tasks` →
```json
[ { "id": "bugfix-negative-qty", "title": "...", "category": "bug_fix",
    "repo": "sample", "difficulty": "medium", "description": "...",
    "hidden_tests": true } ]
```

### `GET /api/benchmark/results` →
```json
{ "aggregates": { "A": { "runs": 3, "completion_rate": 0.66,
      "avg_tests_passed": 4.3, "avg_tokens": 12000, "avg_cost_usd": 0.02,
      "avg_duration_ms": 21000, "avg_tool_calls": 30, "avg_repairs": 1.0,
      "avg_files_modified": 1.3, "avg_graph_queries": 0 },
    "B": {...}, "C": {...} },
  "runs": [ { "run_id": "...", "task": "...", "created_at": "...",
      "systems": { "A": {metrics..., "completion": "success"}, "B": {...}, "C": {...} } } ] }
```

## Error shape
`{ "detail": "human readable message" }` with proper HTTP status.
