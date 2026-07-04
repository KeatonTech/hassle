"""M1 INTEGRATION — the public DSL surface after the three workstreams merge.

These tests lock in the integration decisions the merge forced (regression tests
per R4, since each is a bug the merge surfaced):

- The ``event`` name is the *trigger* builder (DESIGN §5.4). The fire-event
  *action* is a distinct name ``fire_event`` — the two must not collide.
- The ``template`` name is a *single* builder usable both as a value (raw Jinja,
  DESIGN §5.4 "Raw Jinja is always available") and, inside ``when``/``only_if``,
  as a template trigger/condition. One name, one object.
- API smoothing (pre-F3): ``state()`` absorbs the trigger options that lived in
  the ``with_trigger_options`` wrapper; ``service()`` absorbs
  ``response_variable`` / ``continue_on_error`` (no second way to do one thing).
- ``StateExpr`` exposes a public ``entity_id`` accessor (no private-attr reach).
"""

from __future__ import annotations

import hassle
from hassle import (
    event,
    fire_event,
    service,
    state,
    template,
    when,
)
from hassle_core.compiler import compile_registered
from hassle_core.compiler.recording import recording
from hassle_core.compiler.registry import RegisteredObject


def _compile_one(func: object, *, kind: str = "automation", **options: object) -> dict:
    reg = RegisteredObject(
        kind=kind,
        func=func,  # type: ignore[arg-type]
        options=dict(options),
        span=None,
        declared_id=str(options.get("id", getattr(func, "__name__", "x"))),
    )
    result = compile_registered([reg])
    (obj,) = result.objects.values()
    return obj.to_ha()


# --------------------------------------------------------------------------- #
# event / fire_event — the two must be distinct callables (no shadowing).
# --------------------------------------------------------------------------- #
def test_event_is_the_trigger_builder() -> None:
    trig = event("custom_event", event_data={"action": "test"})
    assert trig.to_trigger() == {
        "trigger": "event",
        "event_type": "custom_event",
        "event_data": {"action": "test"},
    }


def test_fire_event_is_the_action_verb() -> None:
    with recording(kind="automation", id="x") as rec:
        fire_event("hassle_custom_event", room="hallway", level=2)
    (node,) = rec.actions
    assert node.body == {
        "event": "hassle_custom_event",
        "event_data": {"room": "hallway", "level": 2},
    }


def test_event_and_fire_event_are_not_the_same_object() -> None:
    assert event is not fire_event
    assert "event" in hassle.__all__
    assert "fire_event" in hassle.__all__


# --------------------------------------------------------------------------- #
# template — one builder, two contexts.
# --------------------------------------------------------------------------- #
def test_template_as_value_is_jinja_string() -> None:
    # As a bare value it IS the {{ ... }} text (str subclass).
    assert template("{{ now().hour }}") == "{{ now().hour }}"


def test_template_as_trigger_and_condition() -> None:
    tmpl = template("{{ is_state('binary_sensor.x', 'on') }}")
    assert tmpl.to_trigger() == {
        "trigger": "template",
        "value_template": "{{ is_state('binary_sensor.x', 'on') }}",
    }
    assert tmpl.to_condition() == {
        "condition": "template",
        "value_template": "{{ is_state('binary_sensor.x', 'on') }}",
    }


def test_template_trigger_compiles_in_when() -> None:
    def auto() -> None:
        when(template("{{ states('sensor.t') | float > 25 }}"))
        service("notify.mobile_app", message="hot")

    body = _compile_one(auto, id="tmpl_trig")
    assert body["triggers"] == [
        {"trigger": "template", "value_template": "{{ states('sensor.t') | float > 25 }}"}
    ]


# --------------------------------------------------------------------------- #
# API smoothing — state() absorbs the trigger options.
# --------------------------------------------------------------------------- #
def test_state_trigger_options_folded_in() -> None:
    trig = state("binary_sensor.motion").to("on", id="motion_on", for_={"minutes": 5})
    assert trig.to_trigger() == {
        "trigger": "state",
        "entity_id": "binary_sensor.motion",
        "to": "on",
        "id": "motion_on",
        # for_ normalizes to the canonical full-unit dict (matches every other
        # trigger builder's `for` emission — see fixtures/dsl/*/expected_ir.json).
        "for": {"hours": 0, "minutes": 5, "seconds": 0},
    }


def test_state_enabled_and_variables_options() -> None:
    trig = state("binary_sensor.x").to("on", enabled=False, variables={"k": "v"})
    body = trig.to_trigger()
    assert body["enabled"] is False
    assert body["variables"] == {"k": "v"}


def test_with_trigger_options_wrapper_is_gone() -> None:
    # The wrapper must not survive on the public surface (no two ways to do it).
    assert not hasattr(hassle, "with_trigger_options")
    assert "with_trigger_options" not in hassle.__all__


# --------------------------------------------------------------------------- #
# API smoothing — service() absorbs response_variable / continue_on_error.
# --------------------------------------------------------------------------- #
def test_service_response_variable_and_continue_on_error() -> None:
    def auto() -> None:
        when(state("binary_sensor.x").to("on"))
        service(
            "climate.get_forecast",
            target={"entity_id": "climate.living_room"},
            response_variable="forecast",
        )
        service("notify.mobile_app", message="done", continue_on_error=True)

    body = _compile_one(auto, id="svc_ext")
    assert body["actions"] == [
        {
            "action": "climate.get_forecast",
            "target": {"entity_id": "climate.living_room"},
            "response_variable": "forecast",
        },
        {
            "action": "notify.mobile_app",
            "data": {"message": "done"},
            "continue_on_error": True,
        },
    ]


def test_service_ext_wrapper_is_gone() -> None:
    assert not hasattr(hassle, "service_ext")
    assert "service_ext" not in hassle.__all__


# --------------------------------------------------------------------------- #
# StateExpr public entity-id accessor (no private-attr reach from templates).
# --------------------------------------------------------------------------- #
def test_state_expr_public_entity_id() -> None:
    expr_state = state("sensor.outdoor_temp")
    assert expr_state.entity_id == "sensor.outdoor_temp"
    # .value uses the public accessor, not the private field.
    assert expr_state.value == "{{ states('sensor.outdoor_temp') | float }}"


# --------------------------------------------------------------------------- #
# hassle_core.dsl_builtins must re-export the *identical* F3 surface as
# hassle.__all__ (reviewer finding: it silently carried only 41 of 72 names).
# --------------------------------------------------------------------------- #
def test_dsl_builtins_parity_with_hassle_all() -> None:
    import hassle_core.dsl_builtins as dsl_builtins

    assert set(dsl_builtins.__all__) == set(hassle.__all__)
    # Every name must also be the *same object* (not a name that merely
    # coincides), so the two modules can never drift into re-exporting
    # different implementations under the same name.
    for name in hassle.__all__:
        assert getattr(dsl_builtins, name) is getattr(hassle, name), name
