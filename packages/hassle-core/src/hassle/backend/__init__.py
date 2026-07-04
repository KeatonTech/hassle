"""The `Backend` seam (F2) and its implementations — DESIGN §8, §4.

Freeze point **F2** (start of M5): the `Backend` Protocol declared here, plus
the plan/apply data model in :mod:`hassle.sync`. M5 built the sync engine
against `FakeBackend` (:mod:`hassle.backend.fake`); M6 adds `DirectBackend`
(:mod:`hassle.backend.direct`) — the real REST/WebSocket transport to HA Core —
as a sibling implementation of the same Protocol. See docs/backend.md.
"""

from __future__ import annotations

from hassle.backend.client import HaClient
from hassle.backend.direct import DirectBackend
from hassle.backend.errors import HaApiError, HaAuthError, HaConnectionError, HaError
from hassle.backend.protocol import Backend

__all__ = [
    "Backend",
    "DirectBackend",
    "HaApiError",
    "HaAuthError",
    "HaClient",
    "HaConnectionError",
    "HaError",
]
