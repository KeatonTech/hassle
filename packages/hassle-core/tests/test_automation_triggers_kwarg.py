"""``triggers=`` decorator metadata — the new canonical DSL form (DESIGN §5.3/§5.5,
docs/internals/dsl-extensions.md).

``@automation`` gains a ``triggers=`` keyword: a list of ``TriggerBuilder``
objects (the same objects ``when()`` accepts), evaluated at decoration time
(i.e. Python-object construction happens when the decorator line itself runs,
before the function body is ever invoked by the compiler). Semantics:
``triggers=`` and ``when()`` COMPOSE — the decorator list's triggers are
recorded first, then any ``when()`` calls inside the body append after them,
in call order. ``when()`` remains fully supported (the frozen top-level DSL
surface forbids removing it) and is still the right tool for a
dynamically-built trigger list.

``@automation(triggers=[...])`` must produce byte-identical IR to the
equivalent ``when(...)`` form.
"""

from __future__ import annotations

from pathlib import Path

from hassle.compiler.bundle import compile_bundle
from hassle.ir import canonical_json


def _write_bundle(tmp_path: Path, code: str) -> Path:
    bundle = tmp_path / "bundle"
    bundle.mkdir(parents=True)
    (bundle / "automation.py").write_text(code, encoding="utf-8")
    return bundle


def test_triggers_kwarg_produces_same_ir_as_when_form(tmp_path: Path) -> None:
    decorator_form = _write_bundle(
        tmp_path / "decorator",
        """
from hassle import automation, service, state

@automation(
    id="hall_light_on_motion",
    alias="Hallway: light on motion",
    triggers=[state("binary_sensor.hall_motion").to("on")],
)
def hall_light_on_motion():
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
    )
    when_form = _write_bundle(
        tmp_path / "when",
        """
from hassle import automation, service, state, when

@automation(id="hall_light_on_motion", alias="Hallway: light on motion")
def hall_light_on_motion():
    when(state("binary_sensor.hall_motion").to("on"))
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
    )

    decorator_result = compile_bundle(decorator_form)
    when_result = compile_bundle(when_form)

    decorator_ir = {k: v.to_ha() for k, v in decorator_result.objects.items()}
    when_ir = {k: v.to_ha() for k, v in when_result.objects.items()}

    assert canonical_json(decorator_ir) == canonical_json(when_ir)


def test_triggers_kwarg_accepts_multiple_triggers_in_order(tmp_path: Path) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, service, state

@automation(
    id="multi",
    alias="Multi",
    triggers=[
        state("binary_sensor.hall_motion").to("on"),
        state("binary_sensor.door").to("off"),
    ],
)
def multi():
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
    )
    result = compile_bundle(bundle)
    (obj,) = result.objects.values()
    triggers = obj.to_ha()["triggers"]
    assert len(triggers) == 2
    assert triggers[0]["entity_id"] == "binary_sensor.hall_motion"
    assert triggers[1]["entity_id"] == "binary_sensor.door"


def test_triggers_kwarg_composes_with_when_decorator_first() -> None:
    # Decorator list's triggers land first, then when()'s append after, in
    # call order -- exercised directly against the recorder (not a full bundle
    # compile) so the composition order is pinned precisely.
    from hassle.compiler.builders import state as state_trigger
    from hassle.compiler.bundle import compile_registered
    from hassle.compiler.recording import when
    from hassle.compiler.registry import RegisteredObject
    from hassle.compiler.spans import capture_span

    def body() -> None:
        when(state_trigger("binary_sensor.door").to("off"))

    reg = RegisteredObject(
        kind="automation",
        func=body,
        options={"id": "compose", "alias": "Compose"},
        span=capture_span(depth=0),
        declared_id="compose",
        decorator_triggers=[state_trigger("binary_sensor.hall_motion").to("on")],
    )
    result = compile_registered([reg])
    (obj,) = result.objects.values()
    triggers = obj.to_ha()["triggers"]
    assert len(triggers) == 2
    assert triggers[0]["entity_id"] == "binary_sensor.hall_motion"
    assert triggers[1]["entity_id"] == "binary_sensor.door"


def test_triggers_kwarg_empty_list_is_same_as_omitting_it(tmp_path: Path) -> None:
    with_empty = _write_bundle(
        tmp_path / "with_empty",
        """
from hassle import automation, service

@automation(id="a", alias="A", triggers=[])
def a():
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
    )
    without = _write_bundle(
        tmp_path / "without",
        """
from hassle import automation, service

@automation(id="a", alias="A")
def a():
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
    )
    with_result = compile_bundle(with_empty)
    without_result = compile_bundle(without)
    with_ir = {k: v.to_ha() for k, v in with_result.objects.items()}
    without_ir = {k: v.to_ha() for k, v in without_result.objects.items()}
    assert canonical_json(with_ir) == canonical_json(without_ir)


def test_triggers_kwarg_only_valid_on_automation_not_script(tmp_path: Path) -> None:
    # `script` has no triggers at all (HA scripts aren't triggered by
    # themselves); `triggers=` on `@script` must still be rejected as an
    # unknown option, exactly like any other bogus kwarg.
    import pytest

    from hassle.compiler.errors import UnknownAutomationOptionError

    bundle = _write_bundle(
        tmp_path,
        """
from hassle import script, service, state

@script(id="a", alias="A", triggers=[state("binary_sensor.x").to("on")])
def a():
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
    )
    with pytest.raises(UnknownAutomationOptionError):
        compile_bundle(bundle)
