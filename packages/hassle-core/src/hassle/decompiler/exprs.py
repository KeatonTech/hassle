"""Decompile a single trigger/condition/action dict to a DSL source expression.

Each ``decompile_*`` function returns a Python source snippet (a single
expression, no trailing newline) that reproduces the given HA dict via the
frozen DSL surface (docs/dsl-extensions.md), or returns ``None`` when the
shape isn't modeled -- the caller falls back to the granular ``raw_*`` escape
hatch (DESIGN §5.8).

Nothing here mutates its input, and nothing depends on wall-clock or
randomness: the same dict always decompiles to the same source string.
"""

from __future__ import annotations

import re
from typing import Any, cast

# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def render_literal(value: Any) -> str:
    """Render a JSON-compatible value as a Python literal (deterministic)."""
    if isinstance(value, dict):
        as_dict = cast("dict[Any, Any]", value)
        items = ", ".join(
            f"{render_literal(k)}: {render_entity_literal_at(k, v)}" for k, v in as_dict.items()
        )
        return "{" + items + "}"
    if isinstance(value, list):
        as_list = cast("list[Any]", value)
        return "[" + ", ".join(render_literal(v) for v in as_list) + "]"
    return repr(value)


# An entity id has the shape `domain.object_id` (DESIGN §5.2): domain is
# `[a-z_]+`, object_id is `(?!_)[\da-z_]+(?<!_)` (may start with a digit,
# never with/ending in an underscore). Anchored so a Jinja template string
# (never a bare "domain.object_id" -- it always has `{{`/other punctuation)
# or a registry UUID (hex, no dot) never matches.
_ENTITY_ID_SHAPE_RE = re.compile(r"^[a-z_]+\.(?!_)[a-z0-9_]+(?<!_)$")


def is_entity_id_string(value: Any) -> bool:
    """True for a bare string matching the ``domain.object_id`` shape."""
    return isinstance(value, str) and bool(_ENTITY_ID_SHAPE_RE.match(value))


def render_entity_ref(entity_id: str) -> str:
    """Render an entity id string as ``e.<domain>.<object_id>`` (or the index
    form ``e.<domain>["<object_id>"]`` for a digit-leading object_id, DESIGN
    §5.2 -- a Python attribute can't start with a digit)."""
    domain, _, object_id = entity_id.partition(".")
    if object_id[0].isdigit():
        return f"e.{domain}[{object_id!r}]"
    return f"e.{domain}.{object_id}"


def render_entity_position(value: Any) -> str:
    """Render a value known to be in an *entity position* (a bare entity id,
    or a list of them -- ``_is_entity_id_shape``'s domain: state()/
    numeric_state() entity args, ``target.entity_id``, ``wait_for_trigger``
    triggers, helper refs). A bare id matching the entity-id shape becomes
    ``e.<domain>.<object_id>``; a list becomes ``[e.a.b, e.c.d]`` (each entry
    rendered independently so a non-conforming entry still round-trips as a
    plain literal rather than dropping data). ``EntityRef`` is a ``str``
    subclass (``hassle.compiler.helpers.EntityRef``), so this substitution
    compiles to the exact same HA value as the literal it replaces -- purely
    cosmetic source-level sugar, zero IR drift.
    """
    if isinstance(value, list):
        items = cast("list[Any]", value)
        return "[" + ", ".join(render_entity_position(v) for v in items) + "]"
    if is_entity_id_string(value):
        return render_entity_ref(value)
    return render_literal(value)


# The one dict key where an entity-position value can appear nested (DESIGN
# §7.3): `target={"entity_id": ...}`. Rendered as a real dict via
# `render_literal`, whose per-key dispatch (`render_entity_literal_at`)
# special-cases this key so `target={"entity_id": e.light.hallway}` -- still
# an ordinary dict literal, `EntityRef` is a `str` subclass, so it compiles
# byte-identical (compile(decompile(x)) == x).
_ENTITY_ID_DICT_KEYS = frozenset({"entity_id"})


def render_entity_literal_at(key: Any, value: Any) -> str:
    """`render_literal`'s per-key dispatch for a dict being rendered: an
    `entity_id` key's value goes through the entity-position renderer;
    everything else renders as an ordinary literal."""
    if key in _ENTITY_ID_DICT_KEYS:
        return render_entity_position(value)
    return render_literal(value)


# Options common to every classic trigger builder (DESIGN §5.4): applied via
# `.with_options(...)` chaining so every builder gets them uniformly.
_COMMON_TRIGGER_OPTIONS = ("id", "enabled", "variables")


def _options_kwargs_src(body: dict[str, Any]) -> list[str]:
    """Render `id=`/`enabled=`/`variables=`/`for_=` kwargs present in ``body``
    (the common trigger options, DESIGN §5.4) as ``key=value`` source fragments."""
    parts: list[str] = []
    for key in _COMMON_TRIGGER_OPTIONS:
        if key in body:
            parts.append(f"{key}={render_literal(body[key])}")
    if "for" in body:
        parts.append(f"for_={_duration_call(body['for'])}")
    return parts


def _with_options_suffix(body: dict[str, Any]) -> str:
    """Build a `.with_options(...)` suffix for any common trigger options present."""
    parts = _options_kwargs_src(body)
    return f".with_options({', '.join(parts)})" if parts else ""


def _duration_call(value: Any) -> str:
    """Render a stored ``for:`` dict as an ``hours``/``minutes``/``seconds`` call
    when it matches that exact shape, else a plain dict literal."""
    if isinstance(value, dict):
        candidate = cast("dict[str, Any]", value)
        if set(candidate) <= {"hours", "minutes", "seconds"} and all(
            isinstance(v, int) for v in candidate.values()
        ):
            h: int = candidate.get("hours", 0)
            m: int = candidate.get("minutes", 0)
            s: int = candidate.get("seconds", 0)
            nonzero: list[tuple[str, int]] = [
                (k, v) for k, v in (("hours", h), ("minutes", m), ("seconds", s)) if v
            ]
            if len(nonzero) == 1:
                name, val = nonzero[0]
                return f"{name}({val!r})"
            if len(nonzero) == 0:
                return "seconds(0)"
    return render_literal(value)


# ---------------------------------------------------------------------------
# purpose-specific triggers/conditions (2026.7+, DESIGN §5.4)
# ---------------------------------------------------------------------------

# Any type string containing a `.` is a purpose-specific vocabulary entry
# (`motion.detected`, `climate.is_target_temperature`, ...); classic
# trigger/condition discriminators are bare words (`state`, `numeric_state`, ...).
_CLASSIC_TRIGGER_TYPES = frozenset(
    {
        "state",
        "numeric_state",
        "time",
        "time_pattern",
        "sun",
        "event",
        "zone",
        "template",
        "webhook",
        "mqtt",
        "calendar",
        "persistent_notification",
        "tag",
        "geo_location",
        "homeassistant",
        "device",
    }
)
_CLASSIC_CONDITION_TYPES = frozenset(
    {
        "state",
        "numeric_state",
        "time",
        "sun",
        "zone",
        "template",
        "device",
        "and",
        "or",
        "not",
        "trigger",
    }
)


def _target_call(target: dict[str, Any]) -> str | None:
    if set(target) == {"area_id"}:
        return f"area({target['area_id']!r})"
    if set(target) == {"floor_id"}:
        return f"floor({target['floor_id']!r})"
    if set(target) == {"label_id"}:
        return f"label({target['label_id']!r})"
    if set(target) == {"device_id"}:
        return f"device_id({target['device_id']!r})"
    if set(target) == {"entity_id"} and isinstance(target["entity_id"], str):
        return render_entity_position(target["entity_id"])
    return None


def decompile_purpose_trigger(body: dict[str, Any]) -> str | None:
    type_string = body.get("trigger")
    if not isinstance(type_string, str) or "." not in type_string:
        return None
    if type_string in _CLASSIC_TRIGGER_TYPES:
        return None
    remaining = dict(body)
    remaining.pop("trigger")
    target = remaining.pop("target", None)
    if target is not None:
        target_src = _target_call(target)
        if target_src is None:
            return None
    behavior = remaining.pop("behavior", None)
    raw_options = remaining.pop("options", None)
    for_ = None
    extra_options: dict[str, Any] = {}
    if raw_options is not None:
        if not isinstance(raw_options, dict):
            return None
        extra_options = dict(cast("dict[str, Any]", raw_options))
        if "for" in extra_options:
            for_ = extra_options.pop("for")
    if remaining:
        return None  # some other field we don't model -> raw fallback
    parts = [repr(type_string)]
    if target is not None:
        parts.append(f"target={_target_call(target)}")
    if behavior is not None:
        parts.append(f"behavior={behavior!r}")
    if for_ is not None:
        parts.append(f"for_={_duration_call(for_)}")
    for key, value in extra_options.items():
        parts.append(f"{key}={render_literal(value)}")
    return f"on({', '.join(parts)})"


def decompile_purpose_condition(body: dict[str, Any]) -> str | None:
    type_string = body.get("condition")
    if not isinstance(type_string, str) or "." not in type_string:
        return None
    if type_string in _CLASSIC_CONDITION_TYPES:
        return None
    remaining = dict(body)
    remaining.pop("condition")
    target = remaining.pop("target", None)
    if target is not None and _target_call(target) is None:
        return None
    if remaining:
        return None
    parts = [repr(type_string)]
    if target is not None:
        parts.append(f"target={_target_call(target)}")
    return f"met({', '.join(parts)})"


# ---------------------------------------------------------------------------
# classic triggers
# ---------------------------------------------------------------------------


def decompile_trigger(body: dict[str, Any]) -> str | None:
    """Decompile one trigger dict to a DSL source expression, or ``None``."""
    ttype = body.get("trigger", body.get("platform"))
    if not isinstance(ttype, str):
        return None

    purpose = decompile_purpose_trigger({**body, "trigger": ttype})
    if purpose is not None:
        return purpose
    if ttype not in _CLASSIC_TRIGGER_TYPES:
        return None

    handler = _TRIGGER_HANDLERS.get(ttype)
    if handler is None:
        return None
    return handler(body)


def _is_entity_id_shape(value: Any) -> bool:
    """True for a bare entity-id string, or a list of them: the HA UI always
    stores entity_id as a list, even for a single entity -- a singleton list
    must decompile back to a list, never normalized to a scalar
    (compile(decompile(x)) == x)."""
    if isinstance(value, str):
        return True
    if isinstance(value, list):
        items = cast("list[Any]", value)
        return all(isinstance(item, str) for item in items)
    return False


def _trig_state(body: dict[str, Any]) -> str | None:
    known = {"trigger", "platform", "entity_id", "to", "from", "id", "enabled", "variables", "for"}
    if not set(body) <= known:
        return None
    entity_id = body.get("entity_id")
    if not _is_entity_id_shape(entity_id):
        return None
    call = f"state({render_entity_position(entity_id)})"
    option_kwargs = _options_kwargs_src(body)
    has_to = "to" in body
    has_from = "from" in body
    if has_to and has_from:
        # `.is_(from_)` sets the trigger `from`; `.to(to_)` chains on top to add
        # `to` -- the common options ride on whichever call comes last.
        call += f".is_({render_literal(body['from'])})"
        args = ", ".join([render_literal(body["to"]), *option_kwargs])
        return call + f".to({args})"
    if has_to:
        args = ", ".join([render_literal(body["to"]), *option_kwargs])
        return call + f".to({args})"
    if has_from:
        args = ", ".join([render_literal(body["from"]), *option_kwargs])
        return call + f".is_({args})"
    suffix = _with_options_suffix(body)
    return call + suffix


def _trig_numeric_state(body: dict[str, Any]) -> str | None:
    known = {
        "trigger",
        "platform",
        "entity_id",
        "attribute",
        "above",
        "below",
        "value_template",
        "for",
        "id",
        "enabled",
        "variables",
    }
    if not set(body) <= known:
        return None
    entity_id = body.get("entity_id")
    if not _is_entity_id_shape(entity_id):
        return None
    parts = [render_entity_position(entity_id)]
    for key in ("attribute", "above", "below", "value_template"):
        if key in body:
            parts.append(f"{key}={render_literal(body[key])}")
    call = f"numeric_state({', '.join(parts)})"
    suffix = _with_options_suffix(body)
    return call + suffix


def _trig_time(body: dict[str, Any]) -> str | None:
    known = {"trigger", "platform", "at", "weekday", "id", "enabled", "variables"}
    if not set(body) <= known or "at" not in body:
        return None
    parts = [f"at={render_literal(body['at'])}"]
    if "weekday" in body:
        # Real-world smoke-test finding: HA's `time` trigger schema also
        # accepts `weekday` (docs/ha-api-notes.md), though it was originally
        # documented condition-only.
        parts.append(f"weekday={render_literal(body['weekday'])}")
    call = f"time({', '.join(parts)})"
    suffix = _with_options_suffix(body)
    return call + suffix


def _trig_time_pattern(body: dict[str, Any]) -> str | None:
    known = {"trigger", "platform", "hours", "minutes", "seconds", "id", "enabled", "variables"}
    if not set(body) <= known:
        return None
    parts = [f"{k}={render_literal(body[k])}" for k in ("hours", "minutes", "seconds") if k in body]
    call = f"time_pattern({', '.join(parts)})"
    suffix = _with_options_suffix(body)
    return call + suffix


def _trig_sun(body: dict[str, Any]) -> str | None:
    known = {
        "trigger",
        "platform",
        "event",
        "offset",
        "id",
        "enabled",
        "variables",
    }
    if not set(body) <= known:
        return None
    parts = [f"{k}={render_literal(body[k])}" for k in ("event", "offset") if k in body]
    call = f"sun({', '.join(parts)})"
    suffix = _with_options_suffix(body)
    return call + suffix


def _trig_event(body: dict[str, Any]) -> str | None:
    known = {"trigger", "platform", "event_type", "event_data", "id", "enabled", "variables"}
    if not set(body) <= known or "event_type" not in body:
        return None
    parts = [repr(body["event_type"])]
    if "event_data" in body:
        parts.append(f"event_data={render_literal(body['event_data'])}")
    call = f"event({', '.join(parts)})"
    suffix = _with_options_suffix(body)
    return call + suffix


def _trig_zone(body: dict[str, Any]) -> str | None:
    known = {"trigger", "platform", "entity_id", "zone", "event", "id", "enabled", "variables"}
    if not set(body) <= known or "entity_id" not in body or "zone" not in body:
        return None
    parts = [repr(body["entity_id"]), f"zone={body['zone']!r}"]
    if "event" in body:
        parts.append(f"event={body['event']!r}")
    call = f"zone({', '.join(parts)})"
    suffix = _with_options_suffix(body)
    return call + suffix


def _trig_template(body: dict[str, Any]) -> str | None:
    known = {"trigger", "platform", "value_template", "id", "enabled", "variables", "for"}
    if not set(body) <= known or "value_template" not in body:
        return None
    call = f"template({body['value_template']!r})"
    suffix = _with_options_suffix(body)
    return call + suffix


def _trig_webhook(body: dict[str, Any]) -> str | None:
    known = {"trigger", "platform", "webhook_id", "id", "enabled", "variables"}
    if not set(body) <= known or "webhook_id" not in body:
        return None
    call = f"webhook({body['webhook_id']!r})"
    suffix = _with_options_suffix(body)
    return call + suffix


def _trig_mqtt(body: dict[str, Any]) -> str | None:
    known = {"trigger", "platform", "topic", "payload", "id", "enabled", "variables"}
    if not set(body) <= known or "topic" not in body:
        return None
    parts = [repr(body["topic"])]
    if "payload" in body:
        parts.append(f"payload={body['payload']!r}")
    call = f"mqtt({', '.join(parts)})"
    suffix = _with_options_suffix(body)
    return call + suffix


def _trig_calendar(body: dict[str, Any]) -> str | None:
    known = {"trigger", "platform", "entity_id", "event", "id", "enabled", "variables"}
    if not set(body) <= known or "entity_id" not in body or "event" not in body:
        return None
    call = f"calendar({body['entity_id']!r}, event={body['event']!r})"
    suffix = _with_options_suffix(body)
    return call + suffix


def _trig_persistent_notification(body: dict[str, Any]) -> str | None:
    known = {
        "trigger",
        "platform",
        "notification_id",
        "update_type",
        "id",
        "enabled",
        "variables",
    }
    if not set(body) <= known:
        return None
    parts = [
        f"{k}={render_literal(body[k])}" for k in ("notification_id", "update_type") if k in body
    ]
    call = f"persistent_notification({', '.join(parts)})"
    suffix = _with_options_suffix(body)
    return call + suffix


def _trig_tag(body: dict[str, Any]) -> str | None:
    known = {"trigger", "platform", "tag_id", "id", "enabled", "variables"}
    if not set(body) <= known or "tag_id" not in body:
        return None
    call = f"tag({body['tag_id']!r})"
    suffix = _with_options_suffix(body)
    return call + suffix


def _trig_geo_location(body: dict[str, Any]) -> str | None:
    known = {"trigger", "platform", "source", "zone", "event", "id", "enabled", "variables"}
    if not set(body) <= known or not {"source", "zone", "event"} <= set(body):
        return None
    call = (
        f"geo_location(source={body['source']!r}, zone={body['zone']!r}, event={body['event']!r})"
    )
    suffix = _with_options_suffix(body)
    return call + suffix


def _trig_homeassistant(body: dict[str, Any]) -> str | None:
    known = {"trigger", "platform", "event", "id", "enabled", "variables"}
    if not set(body) <= known or "event" not in body:
        return None
    event = body["event"]
    if event == "start":
        call = "homeassistant_start()"
    elif event == "shutdown":
        call = "homeassistant_shutdown()"
    else:
        return None
    suffix = _with_options_suffix(body)
    return call + suffix


def _trig_device(body: dict[str, Any]) -> str | None:
    # Device triggers have no stable cross-integration schema (DESIGN §5.4) --
    # never decompiled to `device(...)`; always falls back to raw_trigger. This
    # is a deliberate, tracked coverage exception, not a bug.
    return None


_TRIGGER_HANDLERS = {
    "state": _trig_state,
    "numeric_state": _trig_numeric_state,
    "time": _trig_time,
    "time_pattern": _trig_time_pattern,
    "sun": _trig_sun,
    "event": _trig_event,
    "zone": _trig_zone,
    "template": _trig_template,
    "webhook": _trig_webhook,
    "mqtt": _trig_mqtt,
    "calendar": _trig_calendar,
    "persistent_notification": _trig_persistent_notification,
    "tag": _trig_tag,
    "geo_location": _trig_geo_location,
    "homeassistant": _trig_homeassistant,
    "device": _trig_device,
}


# ---------------------------------------------------------------------------
# classic conditions
# ---------------------------------------------------------------------------


def decompile_condition(body: dict[str, Any]) -> str | None:
    """Decompile one condition dict to a DSL source expression, or ``None``."""
    ctype = body.get("condition")
    if not isinstance(ctype, str):
        return None

    purpose = decompile_purpose_condition(body)
    if purpose is not None:
        return purpose
    if ctype not in _CLASSIC_CONDITION_TYPES:
        return None

    handler = _CONDITION_HANDLERS.get(ctype)
    if handler is None:
        return None
    return handler(body)


def _cond_state(body: dict[str, Any]) -> str | None:
    known = {"condition", "entity_id", "state"}
    if not set(body) <= known or "entity_id" not in body:
        return None
    entity_id = body["entity_id"]
    # `entity_id` (and `state`) accept a list too (docs/ha-api-notes.md §20):
    # the HA UI stores a state CONDITION's fields as lists even for a single
    # entity/value, mirroring the trigger fix (`_is_entity_id_shape`) -- a
    # singleton list must stay a list, never normalized to a scalar
    # (compile(decompile(x)) == x).
    if not _is_entity_id_shape(entity_id):
        return None
    call = f"state({render_entity_position(entity_id)})"
    if "state" in body:
        call += f".is_({render_literal(body['state'])})"
    return call


def _cond_numeric_state(body: dict[str, Any]) -> str | None:
    known = {"condition", "entity_id", "attribute", "above", "below", "value_template"}
    if not set(body) <= known or "entity_id" not in body:
        return None
    parts = [render_entity_position(body["entity_id"])]
    for key in ("attribute", "above", "below", "value_template"):
        if key in body:
            parts.append(f"{key}={render_literal(body[key])}")
    return f"numeric_state({', '.join(parts)})"


def _cond_time(body: dict[str, Any]) -> str | None:
    known = {"condition", "after", "before", "weekday"}
    if not set(body) <= known:
        return None
    parts = [f"{k}={render_literal(body[k])}" for k in ("after", "before", "weekday") if k in body]
    return f"time({', '.join(parts)})"


def _cond_sun(body: dict[str, Any]) -> str | None:
    known = {"condition", "after", "after_offset", "before", "before_offset"}
    if not set(body) <= known:
        return None
    parts = [
        f"{k}={render_literal(body[k])}"
        for k in ("after", "after_offset", "before", "before_offset")
        if k in body
    ]
    return f"sun({', '.join(parts)})"


def _cond_zone(body: dict[str, Any]) -> str | None:
    known = {"condition", "entity_id", "zone"}
    if not set(body) <= known or "entity_id" not in body or "zone" not in body:
        return None
    return f"zone({body['entity_id']!r}, zone={body['zone']!r})"


def _cond_template(body: dict[str, Any]) -> str | None:
    known = {"condition", "value_template"}
    if not set(body) <= known or "value_template" not in body:
        return None
    return f"template({body['value_template']!r})"


def _cond_device(body: dict[str, Any]) -> str | None:
    # Same rationale as `_trig_device`: no stable schema, always raw.
    return None


def _cond_and_or_not(body: dict[str, Any]) -> str | None:
    ctype = body["condition"]
    known = {"condition", "conditions"}
    if not set(body) <= known:
        return None
    inner = body.get("conditions")
    if not isinstance(inner, list):
        return None
    items = cast("list[Any]", inner)
    sub_sources: list[str] = []
    for sub in items:
        if not isinstance(sub, dict):
            return None
        sub_dict = cast("dict[str, Any]", sub)
        src = decompile_condition(sub_dict)
        if src is None:
            return None
        sub_sources.append(src)
    name = {"and": "all_of", "or": "any_of", "not": "not_"}[ctype]
    return f"{name}({', '.join(sub_sources)})"


def _cond_trigger(body: dict[str, Any]) -> str | None:
    known = {"condition", "id"}
    if not set(body) <= known or "id" not in body:
        return None
    return f"trigger_condition({body['id']!r})"


_CONDITION_HANDLERS = {
    "state": _cond_state,
    "numeric_state": _cond_numeric_state,
    "time": _cond_time,
    "sun": _cond_sun,
    "zone": _cond_zone,
    "template": _cond_template,
    "device": _cond_device,
    "and": _cond_and_or_not,
    "or": _cond_and_or_not,
    "not": _cond_and_or_not,
    "trigger": _cond_trigger,
}
