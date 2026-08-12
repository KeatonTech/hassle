"""`@blueprint(triggers=[...])` (docs/internals/blueprints-design.md §8.11).

`@automation` has carried `triggers=` since DESIGN §5.3 and it is the canonical
form the decompiler emits; `@blueprint` lacked it for one accidental reason
only -- `bp_input` was body-scoped, so a trigger built at decoration time had
no way to name an input. That constraint fell with module-scope declarations
(§8.2), and with it the last reason a blueprint body had to open with trigger
calls.

The semantics are `@automation`'s, verbatim: decorator triggers are built at
decoration time and recorded FIRST, then any `when()`/`raw_trigger` calls in
the body append after them, in call order. Nothing here is a second mechanism
-- it is the same `RegisteredObject.decorator_triggers` list, drained by the
same `record_trigger` loop.
"""

from __future__ import annotations

from pathlib import Path

from hassle.compiler.bundle import compile_bundle
from hassle.ir.models import BlueprintConfig

PATH = "local/taps.yaml"
KEY = f"blueprint:automation/{PATH}"


def _bundle(tmp_path: Path, source: str, *, name: str = "b") -> Path:
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    (root / "taps.py").write_text(source, encoding="utf-8")
    return root


def _source(tmp_path: Path, source: str, *, name: str = "b") -> str:
    obj = compile_bundle(_bundle(tmp_path, source, name=name)).objects[KEY]
    assert isinstance(obj, BlueprintConfig)
    assert obj.source is not None
    return obj.source


def _triggers(tmp_path: Path, source: str, *, name: str = "b") -> list[dict[str, object]]:
    from hassle.blueprints import parse_blueprint

    parsed = parse_blueprint(_source(tmp_path, source, name=name), display_path=PATH)
    return list(parsed.body["triggers"])


DECORATOR_ONLY = """\
from hassle import blueprint, service, state


@blueprint(
    domain="automation",
    path="local/taps.yaml",
    name="Taps",
    triggers=[state("binary_sensor.paddle").to("on")],
)
def taps():
    service("light.turn_on", target={"entity_id": "light.hall"})
"""


def test_a_blueprint_can_declare_its_triggers_in_the_decorator(tmp_path: Path) -> None:
    assert _triggers(tmp_path, DECORATOR_ONLY) == [
        {"trigger": "state", "entity_id": "binary_sensor.paddle", "to": "on"}
    ]


def test_the_body_is_then_a_pure_action_sequence(tmp_path: Path) -> None:
    """The point of the change: nothing in the body corresponds to anything
    but a runtime step."""
    src = _source(tmp_path, DECORATOR_ONLY)
    assert "\ntriggers:\n" in src
    assert "\nactions:\n" in src


WHEN_ONLY = """\
from hassle import blueprint, service, state, when


@blueprint(domain="automation", path="local/taps.yaml", name="Taps")
def taps():
    when(state("binary_sensor.paddle").to("on"))
    service("light.turn_on", target={"entity_id": "light.hall"})
"""


def test_the_decorator_form_emits_the_same_bytes_as_the_when_form(tmp_path: Path) -> None:
    """Compile parity is exact, exactly as it is for `@automation`."""
    assert _source(tmp_path, DECORATOR_ONLY, name="deco") == _source(
        tmp_path, WHEN_ONLY, name="body"
    )


COMPOSED = """\
from hassle import blueprint, raw_trigger, service, state, when


@blueprint(
    domain="automation",
    path="local/taps.yaml",
    name="Taps",
    triggers=[
        state("binary_sensor.paddle").to("on").with_options(id="deco_a"),
        state("binary_sensor.paddle").to("off").with_options(id="deco_b"),
    ],
)
def taps():
    when(state("binary_sensor.other").to("on").with_options(id="body_a"))
    raw_trigger({"trigger": "event", "event_type": "custom", "id": "body_b"})
    service("light.turn_on", target={"entity_id": "light.hall"})
"""


def test_decorator_triggers_are_recorded_before_body_triggers(tmp_path: Path) -> None:
    """§8.11's precedence rule, identical to `@automation`'s: the decorator
    list first, then `when()`/`raw_trigger` in call order."""
    assert [t["id"] for t in _triggers(tmp_path, COMPOSED)] == [
        "deco_a",
        "deco_b",
        "body_a",
        "body_b",
    ]


TUPLE_TRIGGERS = """\
from hassle import blueprint, service, state


@blueprint(
    domain="automation",
    path="local/taps.yaml",
    name="Taps",
    triggers=(state("binary_sensor.paddle").to("on"),),
)
def taps():
    service("light.turn_on", target={"entity_id": "light.hall"})
"""


def test_any_sequence_of_trigger_builders_is_accepted(tmp_path: Path) -> None:
    """`Sequence`, not `list` -- `list` is invariant, and a real list of
    `StateExpr` is not assignable to `list[TriggerBuilder]` under pyright
    strict even though every element satisfies the protocol (the same
    widening `@automation(triggers=)` already carries)."""
    assert len(_triggers(tmp_path, TUPLE_TRIGGERS)) == 1


NO_TRIGGERS = """\
from hassle import blueprint, service


@blueprint(domain="automation", path="local/taps.yaml", name="Taps")
def taps():
    service("light.turn_on", target={"entity_id": "light.hall"})
"""


def test_a_blueprint_with_no_triggers_at_all_still_compiles(tmp_path: Path) -> None:
    """An empty section is omitted, not emitted as `triggers: []` (§8.6)."""
    assert "triggers:" not in _source(tmp_path, NO_TRIGGERS)
