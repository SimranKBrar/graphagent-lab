"""Benchmark task catalog (Phase-4 scaffold with one fully-instrumented task).

Categories follow the spec: bug fixing, cross-file refactoring, feature
implementation, dependency updates, regression prevention. Only
`bugfix-single-item-validation` ships fixtures (mock-edit + hidden tests);
the remaining tasks are catalog entries for real-LLM runs and later phases.
"""
from __future__ import annotations

from typing import Any, Optional

SAMPLE_TASK_TEXT = (
    "Bug: orders with a single item bypass item validation in create_order, so invalid "
    "items (quantity of 0 or less, or a negative price) are accepted and processed. "
    "Fix the validation logic so that every item of every order is validated before the "
    "order is created."
)

FLOWGATE_TASK_TEXT = (
    "Bug: an endpoint that has used up its delivery_attempts budget is still "
    "redelivered once, because the dead-letter boundary check in the dispatcher "
    "is off by one. Fix the boundary so another delivery is refused exactly when "
    "delivery_attempts are exhausted, and the endpoint is marked dead-lettered at "
    "that point. The visible suite does not cover this boundary; hidden tests do."
)

TASKS: list[dict[str, Any]] = [
    {
        "id": "bugfix-single-item-validation",
        "title": "Fix validation skipped for single-item orders",
        "category": "bug_fix",
        "repo": "sample",
        "difficulty": "medium",
        "description": ("create_order only validates items when an order contains more "
                        "than one item, so single-item orders accept invalid quantities "
                        "and prices. Ensure validation runs for every item. The visible "
                        "suite does not cover this bug; hidden tests do."),
        "task": SAMPLE_TASK_TEXT,
        "keywords": ["quantity", "validat"],
        "hidden_tests": True,
        "hidden_tests_dir": "hidden_tests",
        "mock_supported": True,
    },
    {
        "id": "bugfix-dead-letter-boundary",
        "title": "Fix off-by-one in the dead-letter boundary",
        "category": "bug_fix",
        "repo": "flowgate",
        "difficulty": "hard",
        "description": ("can_redeliver compares attempts against max_attempts with <=, so "
                        "an endpoint at its delivery_attempts ceiling is granted one extra "
                        "delivery instead of being dead-lettered. The keyword is buried "
                        "under same-named decoy modules (policies/, reporting/), so text "
                        "search leads away from app/dispatcher.py while graph navigation "
                        "reaches it. The visible suite avoids the boundary; hidden tests "
                        "cover it."),
        "task": FLOWGATE_TASK_TEXT,
        "keywords": ["delivery_attempts", "redeliver"],
        "hidden_tests": True,
        "hidden_tests_dir": "hidden_tests_flowgate",
        "mock_supported": True,
    },
    {
        "id": "feature-discount-codes",
        "title": "Implement discount codes for order totals",
        "category": "feature",
        "repo": "sample",
        "difficulty": "medium",
        "description": ("Add support for applying a percentage discount code to an order "
                        "at creation time (e.g. SAVE10 => 10% off the computed total)."),
        "task": ("Add discount code support to create_order: an optional percent-off "
                 "discount may be applied to the computed order total."),
        "keywords": ["discount"],
        "hidden_tests": False,
        "hidden_tests_dir": None,
        "mock_supported": False,
    },
    {
        "id": "refactor-total-calculation",
        "title": "Cross-file refactoring of total computation",
        "category": "refactor",
        "repo": "sample",
        "difficulty": "hard",
        "description": ("Total/price computation is duplicated across modules; extract a "
                        "single implementation and update all call sites without "
                        "behavioral change."),
        "task": ("Refactor the duplicated order total calculation into a single shared "
                 "helper and update every call site, preserving behavior."),
        "keywords": ["duplicated", "helper"],
        "hidden_tests": False,
        "hidden_tests_dir": None,
        "mock_supported": False,
    },
    {
        "id": "regression-inventory-reserve",
        "title": "Regression prevention for inventory reservation",
        "category": "regression_prevention",
        "repo": "sample",
        "difficulty": "medium",
        "description": ("Harden create_order so that a failed save never leaves inventory "
                        "reserved (rollback path), with tests proving no regression."),
        "task": ("Ensure create_order releases reserved inventory when saving the order "
                 "fails, preventing a regression in stock levels."),
        "keywords": ["inventory", "reserved"],
        "hidden_tests": False,
        "hidden_tests_dir": None,
        "mock_supported": False,
    },
    {
        "id": "dependency-update-drop-legacy",
        "title": "Dependency update: remove legacy compatibility layer",
        "category": "dependency_update",
        "repo": "sample",
        "difficulty": "easy",
        "description": ("Remove the deprecated legacy compatibility helpers and migrate "
                        "remaining imports to the current API."),
        "task": ("Remove the deprecated legacy compatibility module and migrate its "
                 "callers to the current API."),
        "keywords": ["legacy", "deprecated"],
        "hidden_tests": False,
        "hidden_tests_dir": None,
        "mock_supported": False,
    },
]


def catalog() -> list[dict[str, Any]]:
    return [
        {key: task.get(key) for key in
         ("id", "title", "category", "repo", "difficulty", "description",
          "task", "hidden_tests", "mock_supported")}
        for task in TASKS
    ]


def find_task(task_text: str) -> Optional[dict[str, Any]]:
    """Match a submitted task against catalog entries by required keywords."""
    lowered = (task_text or "").lower()
    for task in TASKS:
        keywords = task.get("keywords") or []
        if keywords and all(kw in lowered for kw in keywords):
            return task
    return None
