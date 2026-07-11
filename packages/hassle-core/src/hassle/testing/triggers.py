"""Trigger evaluation (DESIGN §10.1 v1 set).

Each function here answers "does this trigger dict match this stimulus?" for
one HA trigger type. Triggers with a `for:` duration don't fire immediately on
match -- they register a pending hold via :class:`PendingFor`, which the
engine schedules and re-validates when it expires (state must still hold).

Anything not in the v1 set (crucially the 2026.7+ purpose-specific
vocabulary) is simply never matched by :func:`matches_state_change` /
:func:`matches_time` / etc. -- those automations are only reachable via
``sim.fire(...)`` (DESIGN §10.1), which the engine handles separately.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast

from hassle.testing.state import StateChange


@dataclass(frozen=True)
class ForDuration:
    hours: int = 0
    minutes: int = 0
    seconds: int = 0

    def total_seconds(self) -> float:
        return self.hours * 3600 + self.minutes * 60 + self.seconds


def for_duration_of(trigger: dict[str, Any]) -> ForDuration | None:
    """Extract a trigger's ``for:`` duration (dict form only, per DESIGN §7.1)."""
    raw = trigger.get("for")
    if raw is None:
        return None
    if isinstance(raw, dict):
        return ForDuration(
            hours=int(raw.get("hours", 0)),  # type: ignore[arg-type]
            minutes=int(raw.get("minutes", 0)),  # type: ignore[arg-type]
            seconds=int(raw.get("seconds", 0)),  # type: ignore[arg-type]
        )
    return None


def parse_offset(value: Any) -> timedelta:
    """Parse a sun trigger/condition's signed ``"±HH:MM:SS"`` offset string.

    Shared by the trigger engine (``offset:``) and the ``sun`` condition
    (``after_offset:``/``before_offset:``) -- both use the identical shape.
    """
    if not isinstance(value, str) or not value:
        return timedelta()
    sign = -1 if value.startswith("-") else 1
    text = value[1:] if value[0] in "+-" else value
    hour, minute, second = (int(p) for p in text.split(":"))
    return sign * timedelta(hours=hour, minutes=minute, seconds=second)


def _trigger_type(trigger: dict[str, Any]) -> Any:
    """The trigger-type discriminator, preferring the canonical ``trigger:``
    key but falling back to the legacy ``platform:`` key.

    docs/ha-api-notes.md: HA's storage normalization rewrites the *outer*
    block key (`trigger` -> `triggers`) but does **not** rewrite the *inner*
    per-item discriminator -- a config authored (or `raw_*`-passed-through)
    with the legacy ``platform:`` key stores and returns that way verbatim.
    The simulator must recognize both forms, or every legacy-authored
    automation in the corpus (`normalize_ha`'s own worked example,
    `automation_state_trigger_basic.json`) would be untestable.
    """
    return trigger.get("trigger", trigger.get("platform"))


def is_state_trigger(trigger: dict[str, Any]) -> bool:
    return _trigger_type(trigger) == "state"


def is_numeric_state_trigger(trigger: dict[str, Any]) -> bool:
    return _trigger_type(trigger) == "numeric_state"


def is_time_trigger(trigger: dict[str, Any]) -> bool:
    return _trigger_type(trigger) == "time"


def is_time_pattern_trigger(trigger: dict[str, Any]) -> bool:
    return _trigger_type(trigger) == "time_pattern"


def is_sun_trigger(trigger: dict[str, Any]) -> bool:
    return _trigger_type(trigger) == "sun"


def is_template_trigger(trigger: dict[str, Any]) -> bool:
    return _trigger_type(trigger) == "template"


def is_event_trigger(trigger: dict[str, Any]) -> bool:
    return _trigger_type(trigger) == "event"


def is_zone_trigger(trigger: dict[str, Any]) -> bool:
    return _trigger_type(trigger) == "zone"


def _entity_ids(trigger: dict[str, Any]) -> list[Any]:
    """A trigger's ``entity_id`` field, normalized to a list (HA accepts both
    a bare string and a list of entity ids)."""
    entity_id: Any = trigger.get("entity_id")
    if isinstance(entity_id, list):
        return cast("list[Any]", entity_id)
    return [entity_id]


def _state_filter_matches(state_filter: Any, state: str | None) -> bool:
    """HA state triggers accept a scalar or a LIST for `from:`/`to:` (match
    any) -- decompiled triggers routinely carry the list form
    (`state([x]).is_(["off"]).to(["on"])`, task #35)."""
    if isinstance(state_filter, list):
        return state in state_filter
    return state == state_filter


def state_trigger_matches(trigger: dict[str, Any], change: StateChange) -> bool:
    """v1 state trigger: entity_id + optional from/to filters, no `for:` here.

    `for:` durations are handled by the engine (a match here starts the hold
    timer; the engine re-checks the state still holds when it expires).
    """
    entities = _entity_ids(trigger)
    if change.entity_id not in entities:
        return False
    to_filter = trigger.get("to")
    from_filter = trigger.get("from")
    if to_filter is not None and not _state_filter_matches(to_filter, change.new.state):
        return False
    if from_filter is not None:
        old_state = change.old.state if change.old is not None else None
        if not _state_filter_matches(from_filter, old_state):
            return False
    if to_filter is None and from_filter is None:
        # No filters at all: HA fires on any actual state-string change.
        old_state = change.old.state if change.old is not None else None
        if old_state == change.new.state:
            return False
    return True


def numeric_state_crosses(trigger: dict[str, Any], change: StateChange) -> bool:
    """Only fires on the crossing edge, never while already above/below (M4 test 1)."""
    entities = _entity_ids(trigger)
    if change.entity_id not in entities:
        return False
    above = trigger.get("above")
    below = trigger.get("below")
    old_value = _as_float(change.old.state if change.old is not None else None)
    new_value = _as_float(change.new.state)
    if new_value is None:
        return False
    was_satisfied = _numeric_satisfied(old_value, above, below)
    is_satisfied = _numeric_satisfied(new_value, above, below)
    return is_satisfied and not was_satisfied


def _numeric_satisfied(value: float | None, above: Any, below: Any) -> bool:
    if value is None:
        return False
    above_ok = above is None or value > float(above)
    below_ok = below is None or value < float(below)
    return above_ok and below_ok


def _as_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def zone_trigger_matches(trigger: dict[str, Any], change: StateChange) -> bool:
    entities = _entity_ids(trigger)
    if change.entity_id not in entities:
        return False
    zone = trigger.get("zone")
    event = trigger.get("event", "enter")
    old_in_zone = change.old is not None and change.old.state == zone
    new_in_zone = change.new.state == zone
    if event == "enter":
        return new_in_zone and not old_in_zone
    return old_in_zone and not new_in_zone


def template_trigger_edge(trigger: dict[str, Any], was_true: bool, is_true: bool) -> bool:
    """Template triggers fire only on the false->true edge (M4 test 1)."""
    return is_true and not was_true


#: Optional entity-state lookup for `time` triggers whose `at:` is an entity
#: id (task #35): returns the entity's state string, or None when unset.
EntityStateResolver = Callable[[str], str | None] | None


def time_matches(
    trigger: dict[str, Any], moment: datetime, *, resolve_entity: EntityStateResolver = None
) -> bool:
    at = trigger.get("at")
    if not isinstance(at, str):
        return False
    if "." in at and not at.replace(".", "").replace(":", "").isdigit():
        # HA also accepts `at: <input_datetime/sensor entity>`: the trigger
        # time is that entity's current state. Unset/unresolvable state (or
        # no resolver wired in) = the trigger simply never fires -- never a
        # parse crash on the entity id (owner field report, task #35).
        if resolve_entity is None:
            return False
        at = resolve_entity(at)
        if at is None:
            return False
    try:
        parts = at.split(":")
        hour, minute = int(parts[0]), int(parts[1])
        second = int(parts[2]) if len(parts) > 2 else 0
    except ValueError:
        return False
    return (moment.hour, moment.minute, moment.second) == (hour, minute, second)


def time_pattern_matches(trigger: dict[str, Any], moment: datetime) -> bool:
    """HA semantics: any field *finer* than the finest one the user specified
    defaults to exactly ``0``, not "matches every value" -- otherwise
    ``time_pattern(minutes="/5")`` would fire every second within a matching
    minute instead of once per matching minute.
    """
    hours_raw = trigger.get("hours")
    minutes_raw = trigger.get("minutes")
    seconds_raw = trigger.get("seconds")
    # Default an unspecified finer field to "0" once any coarser-or-equal
    # field is given (i.e. only fields finer than the finest specified one
    # are left as "any value"). Concretely: minutes unset + seconds unset ->
    # both "any"; minutes set + seconds unset -> seconds defaults to 0;
    # hours set only -> minutes and seconds both default to 0.
    if seconds_raw is None:
        seconds_raw = 0 if (minutes_raw is not None or hours_raw is not None) else None
    if minutes_raw is None:
        minutes_raw = 0 if hours_raw is not None else None

    def _matches(field_value: Any, actual: int) -> bool:
        if field_value is None:
            return True
        text = str(field_value)
        if text.startswith("/"):
            step = int(text[1:])
            return step > 0 and actual % step == 0
        return actual == int(text)

    return (
        _matches(hours_raw, moment.hour)
        and _matches(minutes_raw, moment.minute)
        and _matches(seconds_raw, moment.second)
    )
