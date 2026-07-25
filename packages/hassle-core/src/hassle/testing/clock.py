"""A deterministic fake clock (DESIGN §10.1: no wall-clock, no sleeps).

The simulator's notion of "now" is entirely driven by :meth:`FakeClock.at` /
:meth:`FakeClock.advance`; nothing in this module reads the real system clock.
"""

from __future__ import annotations

from datetime import datetime, timedelta

_DATETIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d")


def parse_datetime(value: str) -> datetime:
    """Parse a ``"YYYY-MM-DD[ HH:MM[:SS]]"`` string (DESIGN §10.2's ``sim.at(...)``)."""
    last_error: ValueError | None = None
    for fmt in _DATETIME_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError as exc:
            last_error = exc
    raise ValueError(
        f"invalid sim.at(...) datetime {value!r}; use 'YYYY-MM-DD HH:MM[:SS]'"
    ) from last_error


class FakeClock:
    """Deterministic clock: starts at an epoch default, moves only via :meth:`advance`."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 1, 1, 0, 0, 0)

    @property
    def now(self) -> datetime:
        return self._now

    def set(self, value: datetime) -> None:
        self._now = value

    def advance(self, delta: timedelta) -> datetime:
        self._now = self._now + delta
        return self._now
