"""The recording-context compiler (DESIGN §5, §7.2) — the M1 core.

Public surface used by the pipeline, the CLI, and the follow-on M1 workstreams:

- :func:`compile_bundle` / :func:`compile_registered` / :class:`CompileResult`
- the recording verbs (:func:`when`, :func:`only_if`) and the ``@automation`` /
  ``@script`` decorators
- the M1-core builders (:func:`state`, :func:`service`, :func:`delay`)
- the extension-point protocols (:class:`TriggerBuilder` / :class:`ConditionBuilder`
  / :class:`ActionBuilder`) and the record functions the builder families call
- the compile errors (:class:`CompileTimeBranchError` et al.)
- :class:`SourceSpan`

Import the *user-facing* names from the top-level :mod:`hassle` package instead;
this module is the implementation home.
"""

from __future__ import annotations

from hassle_core.compiler.actions import delay, service
from hassle_core.compiler.builders import (
    DelayAction,
    ServiceAction,
    StateExpr,
    state,
)
from hassle_core.compiler.bundle import (
    CompileResult,
    compile_bundle,
    compile_registered,
)
from hassle_core.compiler.conditions import (
    TriggerConditionExpr,
    all_of,
    any_of,
    not_,
    trigger_condition,
)
from hassle_core.compiler.durations import hours, minutes, normalize_duration, seconds
from hassle_core.compiler.errors import (
    CompileError,
    CompileTimeBranchError,
    DuplicateObjectError,
    NoRecordingContextError,
    UnknownAutomationOptionError,
)
from hassle_core.compiler.protocols import (
    ActionBuilder,
    ConditionBuilder,
    TriggerBuilder,
)
from hassle_core.compiler.purpose import (
    AreaTarget,
    DeviceIdTarget,
    FloorTarget,
    LabelTarget,
    PurposeCondition,
    PurposeTrigger,
    area,
    device_id,
    floor,
    label,
    met,
    on,
)
from hassle_core.compiler.recording import (
    RecordedNode,
    Recorder,
    only_if,
    record_action,
    record_condition,
    record_trigger,
    recording,
    when,
)
from hassle_core.compiler.registry import (
    RegisteredObject,
    Registry,
    automation,
    current_registry,
    fresh,
    script,
)
from hassle_core.compiler.spans import SourceSpan, capture_span
from hassle_core.compiler.triggers import (
    CalendarTrigger,
    DeviceTrigger,
    EventTrigger,
    GeoLocationTrigger,
    HomeAssistantTrigger,
    MqttTrigger,
    NumericStateExpr,
    PersistentNotificationTrigger,
    SunExpr,
    TagTrigger,
    TemplateExpr,
    TimeExpr,
    TimePatternTrigger,
    TriggerWithOptions,
    WebhookTrigger,
    ZoneExpr,
    calendar,
    device,
    event,
    geo_location,
    homeassistant_shutdown,
    homeassistant_start,
    mqtt,
    numeric_state,
    persistent_notification,
    sun,
    tag,
    template,
    time,
    time_pattern,
    webhook,
    with_trigger_options,
    zone,
)

__all__ = [
    "ActionBuilder",
    "AreaTarget",
    "CalendarTrigger",
    "CompileError",
    "CompileResult",
    "CompileTimeBranchError",
    "ConditionBuilder",
    "DelayAction",
    "DeviceIdTarget",
    "DeviceTrigger",
    "DuplicateObjectError",
    "EventTrigger",
    "FloorTarget",
    "GeoLocationTrigger",
    "HomeAssistantTrigger",
    "LabelTarget",
    "MqttTrigger",
    "NoRecordingContextError",
    "NumericStateExpr",
    "PersistentNotificationTrigger",
    "PurposeCondition",
    "PurposeTrigger",
    "RecordedNode",
    "Recorder",
    "RegisteredObject",
    "Registry",
    "ServiceAction",
    "SourceSpan",
    "StateExpr",
    "SunExpr",
    "TagTrigger",
    "TemplateExpr",
    "TimeExpr",
    "TimePatternTrigger",
    "TriggerBuilder",
    "TriggerConditionExpr",
    "TriggerWithOptions",
    "UnknownAutomationOptionError",
    "WebhookTrigger",
    "ZoneExpr",
    "all_of",
    "any_of",
    "area",
    "automation",
    "calendar",
    "capture_span",
    "compile_bundle",
    "compile_registered",
    "current_registry",
    "delay",
    "device",
    "device_id",
    "event",
    "floor",
    "fresh",
    "geo_location",
    "homeassistant_shutdown",
    "homeassistant_start",
    "hours",
    "label",
    "met",
    "minutes",
    "mqtt",
    "normalize_duration",
    "not_",
    "numeric_state",
    "on",
    "only_if",
    "persistent_notification",
    "record_action",
    "record_condition",
    "record_trigger",
    "recording",
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
