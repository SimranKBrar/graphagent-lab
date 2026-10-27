"""Scripted edit fixtures used by the mock LLM.

A fixture is matched when every keyword appears in the task text AND the
target file exists in the system's workspace. Fixture files live in
`examples/fixtures/` and contain the full post-edit file content.
The optional `repair` block gives the Repair Agent a corrective second pass —
exercised by the sample task, where the naive first edit regresses inventory
behavior that the visible test suite does catch.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .. import config

FIXTURES_DIR = config.EXAMPLES_DIR / "fixtures"


@dataclass
class Fixture:
    task_id: str
    keywords: tuple[str, ...]
    edits: list[dict[str, str]]                      # [{"path": ..., "file": ...}]
    repair: Optional[dict[str, Any]] = None          # {"edits": [...], "target_stage": ..., ...}
    description: str = ""
    hidden_tests_dir: Optional[str] = None           # relative to examples/

    def matches(self, task: str, workspace: Path) -> bool:
        lowered = task.lower()
        if not all(kw in lowered for kw in self.keywords):
            return False
        return all((workspace / edit["path"]).is_file() for edit in self.edits)


FIXTURES: list[Fixture] = [
    Fixture(
        task_id="bugfix-single-item-validation",
        keywords=("quantity", "validat"),
        edits=[{"path": "orders/service.py", "file": "orders_service_v1.py"}],
        repair={
            "edits": [{"path": "orders/service.py", "file": "orders_service_v2.py"}],
            "target_stage": "test",
            "diagnosis": ("The first edit replaced create_order with a simplified version "
                          "that validates items but skips inventory reservation and order "
                          "persistence, so service-level tests fail."),
            "root_cause": ("The rewrite dropped the inventory.reserve() and repository.save() "
                           "calls while fixing validation ordering."),
        },
        description="Naive first fix (v1) + corrective repair (v2) for the validation bug.",
        hidden_tests_dir="hidden_tests",
    ),
    Fixture(
        task_id="bugfix-dead-letter-boundary",
        keywords=("delivery_attempts", "redeliver"),
        edits=[{"path": "app/dispatcher.py", "file": "flowgate_dispatcher_v1.py"}],
        repair={
            "edits": [{"path": "app/dispatcher.py", "file": "flowgate_dispatcher_v2.py"}],
            "target_stage": "test",
            "diagnosis": ("The first edit corrected the budget comparison but dropped the "
                          "store.mark_dead() call, so dead-letter bookkeeping tests fail."),
            "root_cause": ("The rewrite removed the dead-letter side effect while "
                           "tightening the boundary condition."),
        },
        description=("Boundary fix for the flowgate dispatcher: naive v1 drops dead-letter "
                     "bookkeeping, repair v2 restores it."),
        hidden_tests_dir="hidden_tests_flowgate",
    ),
]


def match_fixture(task: str, workspace: Path) -> Optional[Fixture]:
    try:
        ws = Path(workspace).resolve()
    except OSError:
        return None
    for fixture in FIXTURES:
        try:
            if fixture.matches(task, ws):
                return fixture
        except OSError:
            continue
    return None


def load_fixture_content(edit: dict[str, str]) -> str:
    path = FIXTURES_DIR / edit["file"]
    return path.read_text(encoding="utf-8")
