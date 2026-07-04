"""``hassle`` — the user-facing DSL import surface (DESIGN §5.3).

Bundle files write ``from hassle import automation, when, ...``. This package is
the *public* face of the DSL; the machinery lives in :mod:`hassle_core`. Physical
home (decision, M1): a second top-level package shipped inside the ``hassle-core``
distribution (``packages/hassle-core/src/hassle``), so there is exactly one wheel
to install and the public surface and its implementation version together.

``__all__`` here is the **F3 freeze candidate** declared at the end of M1: additions
are allowed in later milestones, changes are not (R5). It is deliberately minimal —
only the M1-core primitives plus the names the two follow-on M1 workstreams
(triggers/conditions, actions/control-flow) will extend. Each of those adds its own
names to this list in its own PR.
"""

from __future__ import annotations

from hassle_core.compiler import (
    CompileTimeBranchError,
    all_of,
    any_of,
    area,
    automation,
    calendar,
    delay,
    device,
    device_id,
    event,
    floor,
    geo_location,
    homeassistant_shutdown,
    homeassistant_start,
    hours,
    label,
    met,
    minutes,
    mqtt,
    not_,
    numeric_state,
    on,
    only_if,
    persistent_notification,
    script,
    seconds,
    service,
    state,
    sun,
    tag,
    template,
    time,
    time_pattern,
    trigger_condition,
    webhook,
    when,
    with_trigger_options,
    zone,
)

# F3 freeze candidate (sorted; ruff RUF022). Grouped by role for the reader:
#   decorators: automation, script
#   recording verbs: when, only_if
#   M1-core builders: state, service, delay
#   classic trigger/condition builders (triggers/conditions workstream, DESIGN §5.4):
#     numeric_state, time, time_pattern, sun, event, zone, template, webhook, mqtt,
#     calendar, persistent_notification, tag, geo_location, homeassistant_start,
#     homeassistant_shutdown, device, trigger_condition
#   condition combinators: any_of, all_of, not_
#   duration helpers: hours, minutes, seconds
#   purpose-specific builders (2026.7+, DESIGN §5.4): on, met, area, floor, label,
#     device_id
#   trap error (assertable by bundles/tests): CompileTimeBranchError
__all__ = [
    "CompileTimeBranchError",
    "all_of",
    "any_of",
    "area",
    "automation",
    "calendar",
    "delay",
    "device",
    "device_id",
    "event",
    "floor",
    "geo_location",
    "homeassistant_shutdown",
    "homeassistant_start",
    "hours",
    "label",
    "met",
    "minutes",
    "mqtt",
    "not_",
    "numeric_state",
    "on",
    "only_if",
    "persistent_notification",
    "script",
    "seconds",
    "service",
    "state",
    "sun",
    "tag",
    "template",
    "time",
    "time_pattern",
    "trigger_condition",
    "webhook",
    "when",
    "with_trigger_options",
    "zone",
]
