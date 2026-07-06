"""The `hassle.__all__` name -> backing golden-case mapping (MILESTONES M9
test 1: "docs build fails if any `hassle.__all__` name lacks a documented
pair").

Curated by hand (not grepped at doc-build time) so the mapping is reviewable
and stable: adding a new name to `hassle.__all__` without adding it here (or
to :data:`EXEMPT_NAMES`, with a real reason) is caught by
``test_docs_dsl_reference.py::test_every_all_name_is_covered_or_exempt``.

Every case listed must be a real directory under ``fixtures/dsl/<case>/``
with a ``bundle/`` (checked by
``test_name_to_cases_only_references_real_fixture_dirs``); the first case in
each name's list is the one :func:`hassle.docs.dsl_reference.generate_dsl_reference`
uses as the "primary" DSL<->YAML pair shown in that name's section (later
cases are listed as "see also").
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Exemptions: names that are not "a construct with a compiled YAML shape" in
# the DSL<->YAML pair sense, so a golden pair doesn't make sense for them.
# ---------------------------------------------------------------------------

#: Compile-time trap/error classes (DESIGN §5.5, dsl-f3.md "Trap / error
#: surface"): these are exceptions a bundle *catches or reads the message
#: of*, not something that compiles to an HA YAML shape. Documented in a
#: dedicated "Trap / error surface" section instead (their own text IS the
#: pair -- what triggers it / what it says).
EXEMPT_NAMES: frozenset[str] = frozenset(
    {
        "CompileTimeBranchError",
        "ElseWithoutIfError",
        "NoParamContextError",
        "PythonMathMisuseError",
        "UnknownFieldError",
        "UnknownParamError",
        # Compile-time guard, not a construct (ux/dsl-ergonomics round):
        "OnlyIfBlockCoverageError",
        # M13: decorator-form template-helper body contract violation.
        "TemplateHelperDecoratorBodyError",
    }
)

# ---------------------------------------------------------------------------
# name -> [golden case names], curated (see module docstring).
# ---------------------------------------------------------------------------

NAME_TO_CASES: dict[str, list[str]] = {
    "Mode": ["mode_enum_parity"],
    "MaxExceeded": ["mode_enum_parity"],
    # constants
    "PI": ["shade_tracks_sun", "math_expr_reference"],
    "E_": ["math_expr_reference"],
    "TAU": ["math_expr_reference"],
    # object decorators / declarations
    "automation": ["state_delay_service", "kitchen_sink_full"],
    "script": ["standalone_scripts"],
    "shared_script": ["shared_script_call"],
    "macro": ["macro_two_callers", "macro_with_args"],
    "raw_automation": ["raw_automation_legacy"],
    "blueprint_automation": ["blueprint_automation"],
    "input_boolean": ["helper_declarations"],
    "input_number": ["helper_declarations"],
    "input_select": ["helper_declarations"],
    "input_text": ["helper_declarations"],
    "input_datetime": ["helper_declarations"],
    "input_button": ["helper_declarations"],
    "counter": ["helper_declarations"],
    "timer": ["helper_declarations"],
    "schedule": ["helper_declarations"],
    # M10: config-entry template-helper declarations
    "template_number": ["template_helper_declarations"],
    "template_sensor": ["template_helper_declarations"],
    "template_binary_sensor": ["template_helper_declarations"],
    "template_select": ["template_helper_declarations"],
    # recording verbs
    "when": ["state_delay_service"],
    "only_if": ["classic_conditions"],
    # core action verbs
    "service": ["state_delay_service"],
    "delay": ["state_delay_service"],
    "variables": ["action_primitives", "math_expr_reference"],
    "stop": ["action_primitives"],
    "fire_event": ["action_primitives"],
    # classic trigger/condition builders
    "state": ["state_delay_service"],
    "numeric_state": ["numeric_state_trigger"],
    "time": ["time_trigger"],
    "time_pattern": ["time_pattern_trigger"],
    "sun": ["sun_trigger"],
    "event": ["event_trigger"],
    "zone": ["zone_trigger"],
    "template": ["template_trigger", "template_expr_golden"],
    "webhook": ["webhook_trigger"],
    "mqtt": ["mqtt_trigger"],
    "calendar": ["calendar_trigger"],
    "persistent_notification": ["persistent_notification_trigger"],
    "tag": ["tag_trigger"],
    "geo_location": ["geo_location_trigger"],
    "homeassistant_start": ["homeassistant_start_trigger"],
    "homeassistant_shutdown": ["homeassistant_shutdown_trigger"],
    "device": ["device_trigger_raw"],
    "trigger_condition": ["classic_conditions"],
    # condition combinators
    "all_of": ["condition_combinators"],
    "any_of": ["condition_combinators"],
    "not_": ["condition_combinators"],
    # purpose-specific builders
    "on": ["purpose_trigger_area_first"],
    "met": ["purpose_condition"],
    "area": ["purpose_trigger_area_first"],
    "floor": ["purpose_trigger_floor_each"],
    "label": ["purpose_trigger_label_all"],
    "device_id": ["purpose_trigger_device"],
    # duration helpers
    "hours": ["helper_declarations"],
    "minutes": ["state_delay_service"],
    "seconds": ["repeat_count"],
    # template expression builder
    "expr": ["template_expr_golden"],
    "param": ["shared_script_call"],
    # runtime-math expression surface
    "sin": ["math_expr_reference"],
    "cos": ["shade_tracks_sun"],
    "tan": ["math_expr_reference"],
    "asin": ["math_expr_reference"],
    "acos": ["math_expr_reference"],
    "atan": ["math_expr_reference"],
    "atan2": ["math_expr_reference"],
    "sqrt": ["math_expr_reference"],
    "log": ["math_expr_reference"],
    "round_": ["shade_tracks_sun"],
    "abs_": ["math_expr_reference"],
    "min_": ["math_expr_reference"],
    "max_": ["math_expr_reference"],
    "as_datetime": ["math_expr_reference"],
    "as_timestamp": ["math_expr_reference"],
    "today_at": ["math_expr_reference"],
    "timedelta_": ["math_expr_reference"],
    "var": ["math_expr_reference"],
    "concat": ["math_expr_reference"],
    # control flow
    "if_then": ["if_then_else"],
    "else_then": ["if_then_else"],
    "else_if": ["if_elseif_else"],
    "choose": ["choose_action"],
    "repeat_count": ["repeat_count"],
    "repeat_while": ["repeat_while"],
    "repeat_until": ["repeat_until"],
    "repeat_for_each": ["repeat_for_each"],
    "parallel": ["parallel_action"],
    "wait_for": ["wait_for_trigger"],
    "wait_template": ["wait_template"],
    # raw escape hatches
    "raw_trigger": ["raw_passthrough"],
    "raw_condition": ["raw_passthrough"],
    "raw_action": ["raw_passthrough"],
}


def missing_names(all_names: list[str]) -> set[str]:
    """Names in ``all_names`` with neither a golden-case mapping nor an
    exemption -- the M9 test 1 coverage gate."""
    return {name for name in all_names if name not in NAME_TO_CASES and name not in EXEMPT_NAMES}
