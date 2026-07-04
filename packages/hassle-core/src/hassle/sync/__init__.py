"""Sync engine (F2 data model + plan/apply/pull logic) — DESIGN §8.

Freeze point **F2** (start of M5): the plan/apply data model exported here,
alongside the `Backend` Protocol in :mod:`hassle.backend`. See docs/backend.md.
"""

from __future__ import annotations

from hassle.sync.models import (
    ApplyOutcome,
    ApplyResult,
    Conflict,
    ConflictKind,
    Manifest,
    ManifestEntry,
    Plan,
    PlanAction,
    PlanEntry,
)

__all__ = [
    "ApplyOutcome",
    "ApplyResult",
    "Conflict",
    "ConflictKind",
    "Manifest",
    "ManifestEntry",
    "Plan",
    "PlanAction",
    "PlanEntry",
]
