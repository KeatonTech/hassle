"""The frozen `Backend` seam and its implementations — DESIGN §8, §4.

The `Backend` Protocol declared here, plus the plan/apply data model in
:mod:`hassle.sync`, are frozen: the sync engine is built against
`FakeBackend` (:mod:`hassle.backend.fake`, in-memory), and `DirectBackend`
(:mod:`hassle.backend.direct`) — the real REST/WebSocket transport to HA Core
— is a sibling implementation of the same Protocol. See docs/backend.md.
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
