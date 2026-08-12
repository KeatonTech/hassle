"""The two trigger-builder sugar gaps that forced `raw_trigger`
(docs/internals/blueprints-design.md §8.11).

A `raw_trigger` call inside a recorder body is metadata masquerading as step
zero: an action call corresponds 1:1 to a runtime step, a trigger declaration
corresponds to nothing in the sequence. Every `raw_trigger` in the consumer
bundle exists because a typed builder could not express one field, so closing
the gaps is what lets a body be a pure action sequence (and lets the trigger
move into the decorator, where it belongs).

Two gaps, both audited against the consumer bundle:

- **`state()` has no `not_from`/`not_to`.** HA's negated siblings of
  `from:`/`to:`, and the only way to say "a real button press, not the
  `unavailable -> unknown` shuffle an HA restart replays". Every button
  automation in the consumer bundle was raw for this one reason.
- **The `template()` TRIGGER has no `for_`.** Every other trigger builder
  takes `for_=`; the template trigger is the one that could not, so a
  "dark for three minutes" trigger had to be a raw dict.

The equivalence tests are the contract that matters: sugar and the raw dict it
replaces must compile to byte-identical IR, or migrating the consumer bundle
would be a behavior change rather than a rewrite.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from hassle.compiler.builders import state
from hassle.compiler.bundle import compile_bundle
from hassle.compiler.durations import minutes
from hassle.compiler.templates import template
from hassle.ir import canonical_json


def _bundle(tmp_path: Path, source: str, *, name: str = "b") -> Path:
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    (root / "auto.py").write_text(source, encoding="utf-8")
    return root


def _ir(tmp_path: Path, source: str, *, name: str) -> str:
    result = compile_bundle(_bundle(tmp_path, source, name=name))
    return canonical_json({key: obj.to_ha() for key, obj in result.objects.items()})


# --- state(): not_from / not_to ---------------------------------------------


def test_not_from_is_carried_into_the_trigger_verbatim() -> None:
    trigger = state("event.paddle").with_options(not_from=["unavailable"]).to_trigger()
    assert trigger["not_from"] == ["unavailable"]


def test_not_to_is_carried_into_the_trigger_verbatim() -> None:
    trigger = state("event.paddle").with_options(not_to=["unknown", "unavailable"]).to_trigger()
    assert trigger["not_to"] == ["unknown", "unavailable"]


def test_a_scalar_negation_stays_a_scalar() -> None:
    """HA's schema takes either; a singleton list must never be flattened, and
    a scalar must never be wrapped -- `compile(decompile(x)) == x`."""
    trigger = state("event.paddle").with_options(not_from="unavailable").to_trigger()
    assert trigger["not_from"] == "unavailable"


def test_both_negations_compose_with_a_trigger_id() -> None:
    trigger = (
        state("event.paddle")
        .with_options(id="up", not_from=["unavailable"], not_to=["unknown", "unavailable"])
        .to_trigger()
    )
    assert trigger == {
        "trigger": "state",
        "entity_id": "event.paddle",
        "not_from": ["unavailable"],
        "not_to": ["unknown", "unavailable"],
        "id": "up",
    }


def test_the_negations_sit_beside_from_and_to_not_among_the_common_options() -> None:
    """They are state-trigger FIELDS (siblings of `from`/`to`), not common
    options like `id`/`for` -- no other trigger type has them."""
    trigger = (
        state("event.paddle")
        .is_("off")
        .to("on", id="up")
        .with_options(not_from=["unavailable"], not_to=["unknown"])
        .to_trigger()
    )
    assert list(trigger) == ["trigger", "entity_id", "from", "to", "not_from", "not_to", "id"]


def test_the_negations_are_trigger_only_and_never_reach_the_condition() -> None:
    """HA's `state` CONDITION schema has no `not_from`/`not_to`."""
    expr = state("event.paddle").is_("on").with_options(not_from=["unavailable"])
    assert expr.to_condition() == {
        "condition": "state",
        "entity_id": "event.paddle",
        "state": "on",
    }


NEGATION_SUGAR = """\
from hassle import automation, state, service


@automation(
    id="paddle_up",
    triggers=[
        state("event.paddle").with_options(
            id="up", not_from=["unavailable"], not_to=["unknown", "unavailable"]
        )
    ],
)
def paddle_up():
    service("light.turn_on", target={"entity_id": "light.hall"})
"""

NEGATION_RAW = """\
from hassle import automation, raw_trigger, service


@automation(id="paddle_up")
def paddle_up():
    raw_trigger(
        {
            "trigger": "state",
            "entity_id": "event.paddle",
            "not_from": ["unavailable"],
            "not_to": ["unknown", "unavailable"],
            "id": "up",
        }
    )
    service("light.turn_on", target={"entity_id": "light.hall"})
"""


def test_the_negation_sugar_compiles_byte_identically_to_the_raw_dict(tmp_path: Path) -> None:
    assert _ir(tmp_path, NEGATION_SUGAR, name="sugar") == _ir(tmp_path, NEGATION_RAW, name="raw")


# --- template(): for_ -------------------------------------------------------


def test_the_template_trigger_takes_a_for_duration() -> None:
    assert template("{{ states('sensor.lux') | float < 40 }}", for_=minutes(3)).to_trigger() == {
        "trigger": "template",
        "value_template": "{{ states('sensor.lux') | float < 40 }}",
        "for": {"hours": 0, "minutes": 3, "seconds": 0},
    }


def test_the_template_for_accepts_every_duration_form_the_state_builder_does() -> None:
    """`for_=` is normalized by the one shared `normalize_duration`, so the
    three input forms are interchangeable here exactly as they are on
    `state(...).to(..., for_=)`."""
    expected = {"hours": 0, "minutes": 3, "seconds": 0}
    assert template("x", for_="00:03:00").to_trigger()["for"] == expected
    assert template("x", for_=timedelta(minutes=3)).to_trigger()["for"] == expected
    assert template("x", for_={"minutes": 3}).to_trigger()["for"] == expected


def test_a_template_without_for_is_unchanged() -> None:
    assert template("{{ 1 > 0 }}").to_trigger() == {
        "trigger": "template",
        "value_template": "{{ 1 > 0 }}",
    }


def test_the_for_never_leaks_into_the_condition_or_the_value(tmp_path: Path) -> None:
    """One object, two serializations (DESIGN §5.4): `for` is a TRIGGER field,
    and the bare value is still the Jinja string it always was."""
    expr = template("{{ 1 > 0 }}", for_=minutes(3))
    assert expr.to_condition() == {"condition": "template", "value_template": "{{ 1 > 0 }}"}
    assert str(expr) == "{{ 1 > 0 }}"


def test_operators_on_a_template_do_not_inherit_its_trigger_for() -> None:
    """A derived expression is a NEW template, not the trigger it came from --
    otherwise a shared module-level constant would smuggle a `for` into every
    expression built from it."""
    base = template("{{ states('sensor.lux') | float < 40 }}", for_=minutes(3))
    assert "for" not in (base & template("{{ 1 > 0 }}")).to_trigger()


TEMPLATE_FOR_SUGAR = """\
from hassle import automation, template, service, minutes


@automation(id="dark_dining", triggers=[template("{{ dark }}", for_=minutes(3))])
def dark_dining():
    service("light.turn_on", target={"entity_id": "light.chandelier"})
"""

TEMPLATE_FOR_RAW = """\
from hassle import automation, raw_trigger, service


@automation(id="dark_dining")
def dark_dining():
    raw_trigger(
        {
            "trigger": "template",
            "value_template": "{{ dark }}",
            "for": {"hours": 0, "minutes": 3, "seconds": 0},
        }
    )
    service("light.turn_on", target={"entity_id": "light.chandelier"})
"""


def test_the_template_for_sugar_compiles_byte_identically_to_the_raw_dict(
    tmp_path: Path,
) -> None:
    assert _ir(tmp_path, TEMPLATE_FOR_SUGAR, name="sugar") == _ir(
        tmp_path, TEMPLATE_FOR_RAW, name="raw"
    )
