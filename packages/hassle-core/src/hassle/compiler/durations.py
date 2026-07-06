"""Duration normalization for trigger `for_=` and the `hours`/`minutes`/`seconds`
DSL helpers (DESIGN §5.4 common trigger options).

HA's stored ``for:`` shape is a dict with all three unit keys present
(``{"hours": 0, "minutes": 5, "seconds": 0}`` — see
``fixtures/configs/automation_purpose_trigger_entity_target.json``). The DSL
accepts three input forms for ergonomics (a ``timedelta``, an ``"HH:MM:SS"``
string, or a partial dict of units) and normalizes all of them to that exact
dict shape so compiler output is byte-stable (R8) regardless of which form the
user wrote.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from hassle.compiler.errors import CompileError
from hassle.compiler.spans import capture_span

DurationLike = "timedelta | str | dict[str, Any]"


class InvalidDurationError(CompileError):
    """A `for_=`/duration value is neither a timedelta, an `HH:MM:SS` string,
    nor a dict of hours/minutes/seconds units (R6: what/where/fix -- M9
    error-message audit finding. Previously a bare `ValueError`/`TypeError`
    with no file:line and no fix hint, reachable from ordinary bundle
    authoring, e.g. `state(x).to("on", for_="5 minutes")`)."""

    def __init__(self, value: Any, span: Any = None) -> None:
        where = f" at {span.file}:{span.line}" if span is not None else ""
        self.value = value
        super().__init__(
            f"Invalid duration value {value!r}{where}. A `for_=`/duration value must be "
            f'a `datetime.timedelta`, an `"HH:MM:SS"` string, or a dict of '
            f"hours/minutes/seconds (e.g. the `hours()`/`minutes()`/`seconds()` helpers). "
            f'Fix: use one of those forms, e.g. `for_=minutes(5)` or `for_="00:05:00"`.'
        )


def _duration_dict(hours: int = 0, minutes: int = 0, seconds: int = 0) -> dict[str, int]:
    return {"hours": hours, "minutes": minutes, "seconds": seconds}


def hours(value: int) -> dict[str, int]:
    """``hours(2)`` -> ``{"hours": 2, "minutes": 0, "seconds": 0}`` (DESIGN §5.4)."""
    return _duration_dict(hours=value)


def minutes(value: int) -> dict[str, int]:
    """``minutes(5)`` -> ``{"hours": 0, "minutes": 5, "seconds": 0}`` (DESIGN §5.4)."""
    return _duration_dict(minutes=value)


def seconds(value: int) -> dict[str, int]:
    """``seconds(30)`` -> ``{"hours": 0, "minutes": 0, "seconds": 30}`` (DESIGN §5.4)."""
    return _duration_dict(seconds=value)


def normalize_duration(value: Any) -> dict[str, int]:
    """Normalize a ``for_=`` value (timedelta/str/dict) to HA's stored dict shape.

    Accepts:
      - a ``datetime.timedelta``,
      - an ``"HH:MM:SS"`` string,
      - a (possibly partial) dict of ``hours``/``minutes``/``seconds`` (as
        produced by :func:`hours`/:func:`minutes`/:func:`seconds`, or authored
        directly by the user).

    Always returns all three keys (matching HA's own normalization) so output
    is deterministic regardless of the input form.
    """
    if isinstance(value, timedelta):
        total_seconds = int(value.total_seconds())
        h, rem = divmod(total_seconds, 3600)
        m, s = divmod(rem, 60)
        return _duration_dict(hours=h, minutes=m, seconds=s)
    if isinstance(value, str):
        parts = value.split(":")
        if len(parts) != 3:
            raise InvalidDurationError(value, capture_span(depth=0))
        try:
            h, m, s = (int(p) for p in parts)
        except ValueError as exc:
            raise InvalidDurationError(value, capture_span(depth=0)) from exc
        return _duration_dict(hours=h, minutes=m, seconds=s)
    if isinstance(value, dict):
        return _duration_dict(
            hours=int(value.get("hours", 0)),  # type: ignore[arg-type]
            minutes=int(value.get("minutes", 0)),  # type: ignore[arg-type]
            seconds=int(value.get("seconds", 0)),  # type: ignore[arg-type]
        )
    raise InvalidDurationError(value, capture_span(depth=0))
