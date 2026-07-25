"""Sync engine (frozen plan/apply data model + plan/apply/pull logic) — DESIGN §8.

The plan/apply data model exported here is frozen, alongside the `Backend`
Protocol in :mod:`hassle.backend`. See docs/internals/backend-protocol.md.
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
