"""Stage 2's two structural guarantees (docs/internals/blueprints-design.md §8.3, §8.5).

§8.5 is the point of the whole design. The field HTTP-400 that motivated
blueprints-as-objects (§0) was an OPTIONAL entity-selector input used as a
literal service target: HA validates the *static* expanded config, so a literal
empty entity id is rejected even inside a runtime-guarded branch. Stage 1 can
only DETECT that after the fact (§6.3). Stage 2 makes it unwritable — the
emitter has no code path that produces a literal empty entity id:

- optional entity input as a service target -> automatically templated via a
  bound variable, the hand-written fix §6.3 prescribes, applied unconditionally;
- optional entity input as a trigger `entity_id` -> a compile error, because
  HA does not template trigger entity ids, so there is no templated escape;
- required entity inputs -> literal everywhere, since they can never be empty.

§8.3 is HA's own rule: `!input` substitutes into YAML nodes, never into the text
inside a template, so a ref must be bound through `variables()` first.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hassle.compiler.blueprint_dsl import (
    BlueprintInputInTemplateError,
    OptionalEntityInputAsTriggerError,
)
from hassle.compiler.bundle import compile_bundle
from hassle.ir.models import BlueprintConfig
from hassle_dev.snapshots import check_snapshot, normalize_error

SNAP_DIR = Path(__file__).resolve().parent / "snapshots" / "errors"

PATH = "local/lights-pause.yaml"
KEY = f"blueprint:automation/{PATH}"

_HEAD = """\
from hassle import blueprint, bp_input, service, when, state, variables


@blueprint(
    domain="automation",
    path="local/lights-pause.yaml",
    name="Lights pause",
)
def lights_pause():
"""


def _bundle(tmp_path: Path, body: str) -> Path:
    root = tmp_path / "bundle"
    root.mkdir(parents=True, exist_ok=True)
    (root / "misc.py").write_text(_HEAD + body, encoding="utf-8")
    return root


def _source(tmp_path: Path, body: str) -> str:
    obj = compile_bundle(_bundle(tmp_path, body)).objects[KEY]
    assert isinstance(obj, BlueprintConfig)
    assert obj.source is not None
    return obj.source


def _normalize(msg: str) -> str:
    return normalize_error(msg, mask_lines_for="misc.py")


# --- §8.5: the optional entity input, as a service target -------------------


OPTIONAL_TARGET = """\
    lights = bp_input("lights", selector={"entity": {"domain": "light"}}, default="")
    when(state("binary_sensor.motion").to("on"))
    service("light.turn_off", target={"entity_id": lights})
"""


def test_an_optional_entity_target_is_emitted_as_a_template_not_a_literal(
    tmp_path: Path,
) -> None:
    src = _source(tmp_path, OPTIONAL_TARGET)
    assert "entity_id: '{{ lights }}'" in src or 'entity_id: "{{ lights }}"' in src
    # The literal form is the one HA rejects with the opaque 400.
    assert "entity_id: !input lights" not in src


def test_the_optional_entity_target_gets_an_automatic_variable_binding(
    tmp_path: Path,
) -> None:
    src = _source(tmp_path, OPTIONAL_TARGET)
    assert "variables:" in src
    assert "lights: !input lights" in src


def test_the_automatic_binding_precedes_the_body_sections(tmp_path: Path) -> None:
    """§8.6 rule 5 — `variables` is the first body section, so it is in scope."""
    src = _source(tmp_path, OPTIONAL_TARGET)
    assert src.index("\nvariables:") < src.index("\ntriggers:")


def test_a_required_entity_target_stays_literal(tmp_path: Path) -> None:
    """A required input can never be empty, so §6.3's failure mode cannot arise."""
    src = _source(
        tmp_path,
        """\
    lights = bp_input("lights", selector={"entity": {"domain": "light"}})
    when(state("binary_sensor.motion").to("on"))
    service("light.turn_off", target={"entity_id": lights})
""",
    )
    assert "entity_id: !input lights" in src
    assert "{{ lights }}" not in src


def test_an_optional_non_entity_input_is_not_templated(tmp_path: Path) -> None:
    """The rule is about entity ids; an optional number is just a default."""
    src = _source(
        tmp_path,
        """\
    step = bp_input("step", selector={"number": {"min": 1, "max": 100}}, default=10)
    when(state("binary_sensor.motion").to("on"))
    service("light.turn_on", target={"entity_id": "light.hall"}, brightness_step_pct=step)
""",
    )
    assert "brightness_step_pct: !input step" in src


# --- §8.5: the optional entity input, as a trigger entity_id ----------------


OPTIONAL_TRIGGER = """\
    lights = bp_input("lights", selector={"entity": {"domain": "light"}}, default="")
    when(state(lights).to("on"))
    service("light.turn_off", target={"entity_id": "light.hall"})
"""


def test_an_optional_entity_input_as_a_trigger_entity_id_is_a_compile_error(
    tmp_path: Path,
) -> None:
    with pytest.raises(OptionalEntityInputAsTriggerError):
        compile_bundle(_bundle(tmp_path, OPTIONAL_TRIGGER))


def test_optional_entity_trigger_message_snapshot(tmp_path: Path) -> None:
    with pytest.raises(OptionalEntityInputAsTriggerError) as excinfo:
        compile_bundle(_bundle(tmp_path, OPTIONAL_TRIGGER))
    check_snapshot(SNAP_DIR, "blueprint_optional_entity_trigger", _normalize(str(excinfo.value)))


def test_a_required_entity_input_as_a_trigger_entity_id_is_fine(tmp_path: Path) -> None:
    src = _source(
        tmp_path,
        """\
    lights = bp_input("lights", selector={"entity": {"domain": "light"}})
    when(state(lights).to("on"))
    service("light.turn_off", target={"entity_id": "light.hall"})
""",
    )
    assert "entity_id: !input lights" in src


# --- §8.3: a ref interpolated into a template -------------------------------


IN_TEMPLATE = """\
    lights = bp_input("lights", selector={"entity": {"domain": "light"}})
    when(state("binary_sensor.motion").to("on"))
    service("light.turn_on", target={"entity_id": f"{{{{ {lights} }}}}"})
"""


def test_a_ref_built_into_a_template_string_is_a_compile_error(tmp_path: Path) -> None:
    with pytest.raises(BlueprintInputInTemplateError):
        compile_bundle(_bundle(tmp_path, IN_TEMPLATE))


def test_ref_in_template_message_snapshot(tmp_path: Path) -> None:
    with pytest.raises(BlueprintInputInTemplateError) as excinfo:
        compile_bundle(_bundle(tmp_path, IN_TEMPLATE))
    check_snapshot(SNAP_DIR, "blueprint_input_in_template", _normalize(str(excinfo.value)))


def test_a_ref_bound_through_variables_then_templated_is_accepted(tmp_path: Path) -> None:
    """The fix the error prescribes has to actually work."""
    src = _source(
        tmp_path,
        """\
    lights = bp_input("lights", selector={"entity": {"domain": "light"}})
    when(state("binary_sensor.motion").to("on"))
    variables(lights=lights)
    service("light.turn_on", target={"entity_id": "{{ lights }}"})
""",
    )
    assert "lights: !input lights" in src
    assert "{{ lights }}" in src
