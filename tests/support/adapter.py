"""Spec constants and the guarded backend import used by every L0 test.

The backend is imported lazily so a missing module becomes a SKIP with a reason, never a
silent pass. Everything here is independent of the code under test: the state and stage
lists come from the project spec (sections 5 and 19), not from backend/app.
"""
from __future__ import annotations

import importlib

import pytest

# Spec section 5 UI states.
UI_STATES = {"waiting", "running", "success", "warning", "failed", "cancelled", "needs_clarification"}

# Canonical 14 stages (ADR-009 / INTERFACE_CONTRACTS s3, settled by Jim in MD-ARCH-002). Spec s5 ends "... verification -> result";
# the canonical list has "simulation" and no separate "result" stage.
PIPELINE_STAGES = [
    "instruction", "tokenization", "interpretation", "structured_task", "schema_validation",
    "feasibility", "grounding", "planning_scene", "ik", "planning", "trajectory_validation",
    "execution", "simulation", "verification",
]


def backend(module: str):
    """Import a backend module or skip the calling test with the exact reason."""
    try:
        return importlib.import_module(module)
    except ModuleNotFoundError as exc:
        if exc.name and (module == exc.name or module.startswith(exc.name + ".")):
            pytest.skip(f"backend module '{module}' not importable yet")
        pytest.skip(f"backend dependency missing for '{module}': {exc.name} (pip install -r backend/requirements.txt)")
