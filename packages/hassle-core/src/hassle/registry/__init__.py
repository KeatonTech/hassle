"""``hassle.registry`` — the entity-indexing runtime shape (part of the frozen
DSL surface, DESIGN §5.2/§5.3) plus the registry-snapshot/validation/
stub-generation modules.

``entities`` is re-exported unchanged from :mod:`hassle.registry._entities`
so ``from hassle.registry import entities as e`` keeps working exactly as
before (docs/dsl-extensions.md).

The snapshot/validation/stub-generation additions live in sibling modules and
are NOT re-exported here (they are imported explicitly, e.g.
``from hassle.registry.snapshot import RegistrySnapshot``), keeping this
top-level namespace's frozen ``entities`` entry point uncluttered.
"""

from __future__ import annotations

from hassle.registry._entities import entities

__all__ = ["entities"]
