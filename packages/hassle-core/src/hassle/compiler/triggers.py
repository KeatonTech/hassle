"""Classic HA trigger builders (DESIGN §5.4) — the triggers/conditions M1 workstream.

Every builder emits the canonical plural HA trigger dict directly
(``{"trigger": "<type>", ...}``, per docs/compiler-api.md §1). Field shapes are
pinned against the fixture corpus (``fixtures/configs/automation_*_trigger.json``).

Common options shared by every classic trigger (DESIGN §5.4): ``for_=`` durations,
trigger ``id=``, ``enabled=``, ``variables=``. These are applied via
:meth:`_TriggerBase.with_options` rather than constructor kwargs so every builder
gets them uniformly without repeating the plumbing.

Dual-purpose builders (``numeric_state``, ``time``, ``sun``, ``zone``,
``template``) implement both ``to_trigger`` and ``to_condition`` (like the
M1-core ``state()``) and keep the ``__bool__`` trap (DESIGN §5.5) so a native
Python ``if`` on one of them fails loudly with ``CompileTimeBranchError``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, TypeVar

from hassle.compiler.durations import normalize_duration
from hassle.compiler.errors import CompileTimeBranchError
from hassle.compiler.spans import capture_span

_Self = TypeVar("_Self", bound="_TriggerBase")

# ---------------------------------------------------------------------------
# Shared base: common trigger options (for_, id, enabled, variables) + the
# CompileTimeBranchError __bool__ trap (DESIGN §5.5), extended to every
# dual-purpose builder in this module.
# ---------------------------------------------------------------------------


class _TriggerBase:
    """Base for classic trigger builders: common-option plumbing + bool trap.

    Subclasses implement ``_trigger_type()`` and ``_trigger_fields()``;
    ``to_trigger`` assembles ``{"trigger": type, **fields, **common_options}``.
    Common options are stored separately from type-specific fields so
    ``with_options`` chaining works uniformly across every builder.
    """

    def __init__(self) -> None:
        self._common: dict[str, Any] = {}

    def with_options(
        self: _Self,
        *,
        id: str | None = None,
        enabled: bool | None = None,
        variables: dict[str, Any] | None = None,
        for_: Any = None,
    ) -> _Self:
        """Attach common trigger options (DESIGN §5.4). Returns ``self`` for chaining."""
        if id is not None:
            self._common["id"] = id
        if enabled is not None:
            self._common["enabled"] = enabled
        if variables is not None:
            self._common["variables"] = variables
        if for_ is not None:
            self._common["for"] = normalize_duration(for_)
        return self

    def _init_for(self, for_: Any) -> None:
        """Set ``for_=`` at construction time (used by ``__init__``, not chaining)."""
        if for_ is not None:
            self._common["for"] = normalize_duration(for_)

    def _trigger_type(self) -> str:  # pragma: no cover - overridden
        raise NotImplementedError

    def _trigger_fields(self) -> dict[str, Any]:  # pragma: no cover - overridden
        raise NotImplementedError

    def to_trigger(self) -> dict[str, Any]:
        body: dict[str, Any] = {"trigger": self._trigger_type(), **self._trigger_fields()}
        body.update(self._common)
        return body

    def _branch_repr(self) -> str:  # pragma: no cover - overridden by subclasses
        return repr(self)

    def __bool__(self) -> bool:
        # DESIGN §5.5 trap-catching, extended to every classic trigger/condition
        # builder: a native Python `if`/`bool()` on a runtime expression must
        # fail loudly rather than silently compiling wrong.
        raise CompileTimeBranchError(self._branch_repr(), capture_span(depth=0))


# ---------------------------------------------------------------------------
# numeric_state — also a condition (dual-purpose, like the core `state()`).
# ---------------------------------------------------------------------------
class NumericStateExpr(_TriggerBase):
    """``numeric_state(entity, above=..., below=..., for_=...)`` — trigger + condition.

    ``entity_id`` accepts a single entity or a sequence (real-world
    smoke-test addition: the HA UI always stores this as a list, even for one
    entity; widened ``list[str]`` -> ``Sequence[str]`` in the task #28
    annotation-truth pass -- see ``StateExpr``'s docstring, ``builders.py``,
    for the invariance rationale).
    """

    def __init__(
        self,
        entity_id: str | Sequence[str],
        *,
        above: float | None = None,
        below: float | None = None,
        value_template: str | None = None,
        attribute: str | None = None,
        for_: Any = None,
    ) -> None:
        super().__init__()
        self._entity_id = entity_id
        self._above = above
        self._below = below
        self._value_template = value_template
        self._attribute = attribute
        self._init_for(for_)

    def _trigger_type(self) -> str:
        return "numeric_state"

    def _trigger_fields(self) -> dict[str, Any]:
        return self._fields()

    def _fields(self) -> dict[str, Any]:
        fields: dict[str, Any] = {"entity_id": self._entity_id}
        if self._attribute is not None:
            fields["attribute"] = self._attribute
        if self._above is not None:
            fields["above"] = self._above
        if self._below is not None:
            fields["below"] = self._below
        if self._value_template is not None:
            fields["value_template"] = self._value_template
        return fields

    def to_condition(self) -> dict[str, Any]:
        return {"condition": "numeric_state", **self._fields()}

    def _branch_repr(self) -> str:
        return f"numeric_state({self._entity_id!r})"


def numeric_state(
    entity_id: str | Sequence[str],
    *,
    above: float | None = None,
    below: float | None = None,
    value_template: str | None = None,
    attribute: str | None = None,
    for_: Any = None,
) -> NumericStateExpr:
    """Build a ``numeric_state`` trigger/condition (DESIGN §5.4).

    ``attribute=`` (M1.1 addition) reads an entity attribute instead of its
    main state (HA's ``numeric_state`` schema field of the same name; see
    ``fixtures/dsl/shade_tracks_sun``'s sun-elevation condition). ``entity_id``
    accepts a sequence too (real-world smoke-test addition, same rationale as
    ``state()``).
    """
    return NumericStateExpr(
        entity_id,
        above=above,
        below=below,
        value_template=value_template,
        attribute=attribute,
        for_=for_,
    )


# ---------------------------------------------------------------------------
# time — also a condition.
# ---------------------------------------------------------------------------
class TimeExpr(_TriggerBase):
    """``time(at=..., after=..., before=..., weekday=...)`` — trigger + condition.

    ``at=`` is trigger-only; ``after=``/``before=`` are condition-only (DESIGN
    §5.4 / fixture corpus shapes). ``weekday=`` was originally documented as
    condition-only too, but a real-world smoke-test fixture
    (``automation_time_trigger_weekday_and_entity_at.json``) showed HA's
    ``time`` *trigger* schema also accepts ``weekday`` (a day-abbreviation-list
    filter on the fixed-time trigger, e.g. weekday-scoped wakeups) — recorded
    as a DESIGN §5.4 deviation in docs/ha-api-notes.md. ``at=`` also accepts an
    entity reference (``input_datetime.x``, HA's schedule-driven-wakeup shape)
    since it's typed as a plain ``str``, same as a literal time string. A
    single builder exposes all of them; each serialization method emits only
    its relevant subset.
    """

    def __init__(
        self,
        *,
        at: str | None = None,
        after: str | None = None,
        before: str | None = None,
        weekday: list[str] | None = None,
    ) -> None:
        super().__init__()
        self._at = at
        self._after = after
        self._before = before
        self._weekday = weekday

    def _trigger_type(self) -> str:
        return "time"

    def _trigger_fields(self) -> dict[str, Any]:
        fields: dict[str, Any] = {}
        if self._at is not None:
            fields["at"] = self._at
        if self._weekday is not None:
            fields["weekday"] = self._weekday
        return fields

    def to_condition(self) -> dict[str, Any]:
        fields: dict[str, Any] = {"condition": "time"}
        if self._after is not None:
            fields["after"] = self._after
        if self._before is not None:
            fields["before"] = self._before
        if self._weekday is not None:
            fields["weekday"] = self._weekday
        return fields

    def _branch_repr(self) -> str:
        return "time(...)"


def time(
    *,
    at: str | None = None,
    after: str | None = None,
    before: str | None = None,
    weekday: list[str] | None = None,
) -> TimeExpr:
    """Build a ``time`` trigger/condition (DESIGN §5.4)."""
    return TimeExpr(at=at, after=after, before=before, weekday=weekday)


# ---------------------------------------------------------------------------
# time_pattern — trigger only.
# ---------------------------------------------------------------------------
class TimePatternTrigger(_TriggerBase):
    def __init__(
        self,
        *,
        hours: str | None = None,
        minutes: str | None = None,
        seconds: str | None = None,
    ) -> None:
        super().__init__()
        self._hours = hours
        self._minutes = minutes
        self._seconds = seconds

    def _trigger_type(self) -> str:
        return "time_pattern"

    def _trigger_fields(self) -> dict[str, Any]:
        fields: dict[str, Any] = {}
        if self._hours is not None:
            fields["hours"] = self._hours
        if self._minutes is not None:
            fields["minutes"] = self._minutes
        if self._seconds is not None:
            fields["seconds"] = self._seconds
        return fields

    def _branch_repr(self) -> str:
        return "time_pattern(...)"


def time_pattern(
    *, hours: str | None = None, minutes: str | None = None, seconds: str | None = None
) -> TimePatternTrigger:
    """Build a ``time_pattern`` trigger (DESIGN §5.4)."""
    return TimePatternTrigger(hours=hours, minutes=minutes, seconds=seconds)


# ---------------------------------------------------------------------------
# sun — also a condition.
# ---------------------------------------------------------------------------
class SunExpr(_TriggerBase):
    def __init__(
        self,
        *,
        event: str | None = None,
        offset: str | None = None,
        after: str | None = None,
        after_offset: str | None = None,
        before: str | None = None,
        before_offset: str | None = None,
    ) -> None:
        super().__init__()
        self._event = event
        self._offset = offset
        self._after = after
        self._after_offset = after_offset
        self._before = before
        self._before_offset = before_offset

    def _trigger_type(self) -> str:
        return "sun"

    def _trigger_fields(self) -> dict[str, Any]:
        fields: dict[str, Any] = {}
        if self._event is not None:
            fields["event"] = self._event
        if self._offset is not None:
            fields["offset"] = self._offset
        return fields

    def to_condition(self) -> dict[str, Any]:
        fields: dict[str, Any] = {"condition": "sun"}
        if self._after is not None:
            fields["after"] = self._after
        if self._after_offset is not None:
            fields["after_offset"] = self._after_offset
        if self._before is not None:
            fields["before"] = self._before
        if self._before_offset is not None:
            fields["before_offset"] = self._before_offset
        return fields

    def _branch_repr(self) -> str:
        return "sun(...)"


def sun(
    *,
    event: str | None = None,
    offset: str | None = None,
    after: str | None = None,
    after_offset: str | None = None,
    before: str | None = None,
    before_offset: str | None = None,
) -> SunExpr:
    """Build a ``sun`` trigger/condition (DESIGN §5.4)."""
    return SunExpr(
        event=event,
        offset=offset,
        after=after,
        after_offset=after_offset,
        before=before,
        before_offset=before_offset,
    )


# ---------------------------------------------------------------------------
# event — trigger only.
# ---------------------------------------------------------------------------
class EventTrigger(_TriggerBase):
    def __init__(self, event_type: str, *, event_data: dict[str, Any] | None = None) -> None:
        super().__init__()
        self._event_type = event_type
        self._event_data = event_data

    def _trigger_type(self) -> str:
        return "event"

    def _trigger_fields(self) -> dict[str, Any]:
        fields: dict[str, Any] = {"event_type": self._event_type}
        if self._event_data is not None:
            fields["event_data"] = self._event_data
        return fields

    def _branch_repr(self) -> str:
        return f"event({self._event_type!r})"


def event(event_type: str, *, event_data: dict[str, Any] | None = None) -> EventTrigger:
    """Build an ``event`` trigger (DESIGN §5.4)."""
    return EventTrigger(event_type, event_data=event_data)


# ---------------------------------------------------------------------------
# zone — also a condition.
# ---------------------------------------------------------------------------
class ZoneExpr(_TriggerBase):
    def __init__(self, entity_id: str, *, zone: str, event: str | None = None) -> None:
        super().__init__()
        self._entity_id = entity_id
        self._zone = zone
        self._event = event

    def _trigger_type(self) -> str:
        return "zone"

    def _trigger_fields(self) -> dict[str, Any]:
        fields: dict[str, Any] = {"entity_id": self._entity_id, "zone": self._zone}
        if self._event is not None:
            fields["event"] = self._event
        return fields

    def to_condition(self) -> dict[str, Any]:
        return {"condition": "zone", "entity_id": self._entity_id, "zone": self._zone}

    def _branch_repr(self) -> str:
        return f"zone({self._entity_id!r}, zone={self._zone!r})"


def zone(entity_id: str, *, zone: str, event: str | None = None) -> ZoneExpr:
    """Build a ``zone`` trigger/condition (DESIGN §5.4)."""
    return ZoneExpr(entity_id, zone=zone, event=event)


# ---------------------------------------------------------------------------
# template — raw Jinja string; also a condition.
# ---------------------------------------------------------------------------
# `template()` (trigger/condition) is the single str-subclass builder in
# `templates.py` — it implements `to_trigger`/`to_condition` there, so the
# template trigger and the raw-Jinja value are one object (DESIGN §5.4). This
# module deliberately does not define its own `template`/`TemplateExpr`.


# ---------------------------------------------------------------------------
# webhook — trigger only.
# ---------------------------------------------------------------------------
class WebhookTrigger(_TriggerBase):
    def __init__(self, webhook_id: str) -> None:
        super().__init__()
        self._webhook_id = webhook_id

    def _trigger_type(self) -> str:
        return "webhook"

    def _trigger_fields(self) -> dict[str, Any]:
        return {"webhook_id": self._webhook_id}

    def _branch_repr(self) -> str:
        return f"webhook({self._webhook_id!r})"


def webhook(webhook_id: str) -> WebhookTrigger:
    """Build a ``webhook`` trigger (DESIGN §5.4)."""
    return WebhookTrigger(webhook_id)


# ---------------------------------------------------------------------------
# mqtt — trigger only.
# ---------------------------------------------------------------------------
class MqttTrigger(_TriggerBase):
    def __init__(self, topic: str, *, payload: str | None = None) -> None:
        super().__init__()
        self._topic = topic
        self._payload = payload

    def _trigger_type(self) -> str:
        return "mqtt"

    def _trigger_fields(self) -> dict[str, Any]:
        fields: dict[str, Any] = {"topic": self._topic}
        if self._payload is not None:
            fields["payload"] = self._payload
        return fields

    def _branch_repr(self) -> str:
        return f"mqtt({self._topic!r})"


def mqtt(topic: str, *, payload: str | None = None) -> MqttTrigger:
    """Build an ``mqtt`` trigger (DESIGN §5.4)."""
    return MqttTrigger(topic, payload=payload)


# ---------------------------------------------------------------------------
# calendar — trigger only.
# ---------------------------------------------------------------------------
class CalendarTrigger(_TriggerBase):
    def __init__(self, entity_id: str, *, event: str) -> None:
        super().__init__()
        self._entity_id = entity_id
        self._event = event

    def _trigger_type(self) -> str:
        return "calendar"

    def _trigger_fields(self) -> dict[str, Any]:
        return {"entity_id": self._entity_id, "event": self._event}

    def _branch_repr(self) -> str:
        return f"calendar({self._entity_id!r})"


def calendar(entity_id: str, *, event: str) -> CalendarTrigger:
    """Build a ``calendar`` trigger (DESIGN §5.4)."""
    return CalendarTrigger(entity_id, event=event)


# ---------------------------------------------------------------------------
# persistent_notification — trigger only.
# ---------------------------------------------------------------------------
class PersistentNotificationTrigger(_TriggerBase):
    def __init__(
        self, *, notification_id: str | None = None, update_type: str | None = None
    ) -> None:
        super().__init__()
        self._notification_id = notification_id
        self._update_type = update_type

    def _trigger_type(self) -> str:
        return "persistent_notification"

    def _trigger_fields(self) -> dict[str, Any]:
        fields: dict[str, Any] = {}
        if self._notification_id is not None:
            fields["notification_id"] = self._notification_id
        if self._update_type is not None:
            fields["update_type"] = self._update_type
        return fields

    def _branch_repr(self) -> str:
        return "persistent_notification(...)"


def persistent_notification(
    *, notification_id: str | None = None, update_type: str | None = None
) -> PersistentNotificationTrigger:
    """Build a ``persistent_notification`` trigger (DESIGN §5.4)."""
    return PersistentNotificationTrigger(notification_id=notification_id, update_type=update_type)


# ---------------------------------------------------------------------------
# tag — trigger only.
# ---------------------------------------------------------------------------
class TagTrigger(_TriggerBase):
    def __init__(self, tag_id: str) -> None:
        super().__init__()
        self._tag_id = tag_id

    def _trigger_type(self) -> str:
        return "tag"

    def _trigger_fields(self) -> dict[str, Any]:
        return {"tag_id": self._tag_id}

    def _branch_repr(self) -> str:
        return f"tag({self._tag_id!r})"


def tag(tag_id: str) -> TagTrigger:
    """Build a ``tag`` trigger (DESIGN §5.4)."""
    return TagTrigger(tag_id)


# ---------------------------------------------------------------------------
# geo_location — trigger only.
# ---------------------------------------------------------------------------
class GeoLocationTrigger(_TriggerBase):
    def __init__(self, *, source: str, zone: str, event: str) -> None:
        super().__init__()
        self._source = source
        self._zone = zone
        self._event = event

    def _trigger_type(self) -> str:
        return "geo_location"

    def _trigger_fields(self) -> dict[str, Any]:
        return {"source": self._source, "zone": self._zone, "event": self._event}

    def _branch_repr(self) -> str:
        return f"geo_location(source={self._source!r})"


def geo_location(*, source: str, zone: str, event: str) -> GeoLocationTrigger:
    """Build a ``geo_location`` trigger (DESIGN §5.4)."""
    return GeoLocationTrigger(source=source, zone=zone, event=event)


# ---------------------------------------------------------------------------
# homeassistant start/shutdown — trigger only.
# ---------------------------------------------------------------------------
class HomeAssistantTrigger(_TriggerBase):
    def __init__(self, event: str) -> None:
        super().__init__()
        self._event = event

    def _trigger_type(self) -> str:
        return "homeassistant"

    def _trigger_fields(self) -> dict[str, Any]:
        return {"event": self._event}

    def _branch_repr(self) -> str:
        return f"homeassistant(event={self._event!r})"


def homeassistant_start() -> HomeAssistantTrigger:
    """Build a ``homeassistant`` ``start`` trigger (DESIGN §5.4)."""
    return HomeAssistantTrigger("start")


def homeassistant_shutdown() -> HomeAssistantTrigger:
    """Build a ``homeassistant`` ``shutdown`` trigger (DESIGN §5.4)."""
    return HomeAssistantTrigger("shutdown")


# ---------------------------------------------------------------------------
# device — raw dict passthrough (device triggers have no stable typed schema).
# ---------------------------------------------------------------------------
class DeviceTrigger(_TriggerBase):
    """``device({...})`` — raw passthrough (DESIGN §5.4: "device() (raw passthrough)").

    Device triggers/conditions/actions are integration-specific dicts with no
    stable cross-integration schema; the DSL stores the dict verbatim.
    """

    def __init__(self, fields: dict[str, Any]) -> None:
        super().__init__()
        self._raw_fields = dict(fields)

    def _trigger_type(self) -> str:
        return "device"

    def _trigger_fields(self) -> dict[str, Any]:
        return dict(self._raw_fields)

    def _branch_repr(self) -> str:
        return "device(...)"


def device(fields: dict[str, Any]) -> DeviceTrigger:
    """Build a raw-passthrough ``device`` trigger (DESIGN §5.4)."""
    return DeviceTrigger(fields)
