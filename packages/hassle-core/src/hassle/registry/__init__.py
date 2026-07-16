"""``hassle.registry`` — the M1 entity-indexing runtime shape (F3-frozen, DESIGN
§5.2/§5.3) plus the M3 registry-snapshot/validation/stub-generation modules.

``entities`` is re-exported unchanged from :mod:`hassle.registry._entities`
(the module this package replaces) so ``from hassle.registry import entities
as e`` keeps working exactly as before (docs/dsl-extensions.md) — this package split
is purely a refactor, never a behavior change to the frozen surface.

The M3 additions live in sibling modules and are NOT re-exported here (they
are imported explicitly, e.g. ``from hassle.registry.snapshot import
RegistrySnapshot``), keeping this top-level namespace's frozen ``entities``
entry point uncluttered.
"""

from __future__ import annotations

from hassle.registry._entities import entities

__all__ = ["entities"]
