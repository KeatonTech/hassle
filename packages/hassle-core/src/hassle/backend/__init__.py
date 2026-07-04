"""The `Backend` seam (F2) — DESIGN §8, §4.

Freeze point **F2** (start of M5): the `Backend` Protocol declared here, plus
the plan/apply data model in :mod:`hassle.sync`. M5 builds the sync engine
against `FakeBackend` (:mod:`hassle.backend.fake`); M6 builds `DirectBackend`
against the same Protocol, independently. See docs/backend.md.
"""

from __future__ import annotations

from hassle.backend.protocol import Backend

__all__ = ["Backend"]
