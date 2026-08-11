"""Stage 2: blueprints AUTHORED IN THE DSL (docs/internals/blueprints-design.md §8).

Slice 1 — the authoring surface and the emitter:

- ``@blueprint(...)`` registers a whole object, the same seam
  ``@blueprint_automation`` uses (``raw_automation.py``'s Registration note), so
  it lands in ``CompileResult.objects`` under stage 1's own
  ``blueprint:<domain>/<path>`` key and every stage-1 consumer keeps working.
- ``bp_input(...)`` returns an ``InputRef`` placeholder that compiles to an
  ``!input <name>`` YAML node.
- The emitted ``source`` is a DETERMINISTIC artifact (§8.6): byte-stable across
  compiles, inputs in declaration order, fixed metadata and section order, and
  a header comment that names the Python source without embedding a timestamp.
- Nothing is written into ``blueprints/`` — the compiled object is the source
  of truth (§8.6).
"""

from __future__ import annotations

import re
from pathlib import Path

from hassle.blueprints import blueprint_metadata, parse_blueprint
from hassle.compiler.bundle import compile_bundle
from hassle.ir.models import BlueprintConfig

PATH = "local/room-switch-controls.yaml"
KEY = f"blueprint:automation/{PATH}"

# Declaration order is deliberately NOT alphabetical: `switch_entity` before
# `room_light` before `dim_step_pct` is what §8.6 rule 3 must preserve, and
# sorting would reorder it visibly.
BLUEPRINT_DSL = '''\
"""A DSL-authored blueprint."""

from hassle import blueprint, bp_input, service, when, state


@blueprint(
    domain="automation",
    path="local/room-switch-controls.yaml",
    name="Room switch controls",
    description="Tap a wall switch to drive a room's light.",
    mode="restart",
)
def room_switch_controls():
    switch_entity = bp_input(
        "switch_entity",
        selector={"entity": {"filter": [{"domain": "sensor"}]}},
        description="The wall switch.",
    )
    room_light = bp_input(
        "room_light",
        selector={"entity": {"filter": [{"domain": "light"}]}},
    )
    dim_step_pct = bp_input(
        "dim_step_pct",
        selector={"number": {"min": 1, "max": 100}},
        default=10,
    )
    when(state(switch_entity).to("on"))
    service(
        "light.turn_on",
        target={"entity_id": room_light},
        brightness_step_pct=dim_step_pct,
    )
'''


def _bundle(tmp_path: Path, *, dsl: str = BLUEPRINT_DSL) -> Path:
    root = tmp_path / "bundle"
    root.mkdir(parents=True, exist_ok=True)
    (root / "switches.py").write_text(dsl, encoding="utf-8")
    return root


def _compiled(tmp_path: Path, *, dsl: str = BLUEPRINT_DSL) -> BlueprintConfig:
    result = compile_bundle(_bundle(tmp_path, dsl=dsl))
    obj = result.objects[KEY]
    assert isinstance(obj, BlueprintConfig)
    return obj


# --- registration: a DSL blueprint is a stage-1 object ----------------------


def test_a_dsl_blueprint_registers_under_the_stage_1_object_key(tmp_path: Path) -> None:
    result = compile_bundle(_bundle(tmp_path))
    assert KEY in result.objects


def test_the_registered_object_carries_the_declared_domain_and_path(tmp_path: Path) -> None:
    obj = _compiled(tmp_path)
    assert obj.domain == "automation"
    assert obj.path == PATH


def test_no_file_is_written_into_the_bundles_blueprints_directory(tmp_path: Path) -> None:
    """§8.6: the compiled object is the source of truth, not a generated file."""
    root = _bundle(tmp_path)
    compile_bundle(root)
    assert not (root / "blueprints").exists()


# --- the emitted document ---------------------------------------------------


def test_the_emitted_source_parses_as_a_blueprint(tmp_path: Path) -> None:
    obj = _compiled(tmp_path)
    parsed = parse_blueprint(obj.source, display_path=PATH)
    assert set(parsed.inputs) == {"switch_entity", "room_light", "dim_step_pct"}
    assert blueprint_metadata(obj.source)["name"] == "Room switch controls"


def test_inputs_keep_declaration_order_not_alphabetical_order(tmp_path: Path) -> None:
    """§8.6 rule 3 — declaration order is what the HA UI shows the user."""
    obj = _compiled(tmp_path)
    assert list(obj.inputs) == ["switch_entity", "room_light", "dim_step_pct"]


def test_a_required_input_is_distinguishable_from_an_optional_one(tmp_path: Path) -> None:
    """§8.2 — `UNSET`, not `None`, marks required (stage 1 relies on this)."""
    obj = _compiled(tmp_path)
    assert "default" not in obj.inputs["switch_entity"]
    assert obj.inputs["dim_step_pct"]["default"] == 10


def test_refs_compile_to_input_tags_not_quoted_strings(tmp_path: Path) -> None:
    obj = _compiled(tmp_path)
    assert "entity_id: !input room_light" in obj.source
    assert "!input" in obj.source
    # A quoted tag would be read by HA as the literal text.
    assert "'!input" not in obj.source
    assert '"!input' not in obj.source


def test_the_header_comment_names_the_python_source(tmp_path: Path) -> None:
    obj = _compiled(tmp_path)
    first = obj.source.splitlines()[0]
    assert first.startswith("#")
    assert "switches.py" in obj.source.splitlines()[1]


def test_the_header_carries_no_timestamp_or_absolute_path(tmp_path: Path) -> None:
    """§8.6 rule 1 — the classic byte-stability traps, stated so nobody adds one.

    The bundle-relative path is fine (and wanted); the absolute checkout path is
    not, and neither is anything clock-shaped.
    """
    obj = _compiled(tmp_path)
    header = "\n".join(obj.source.splitlines()[:3])
    assert str(tmp_path) not in header
    assert not re.search(r"\d{4}-\d{2}-\d{2}|\d{10}", header)


def test_metadata_and_body_sections_are_emitted_in_the_fixed_order(tmp_path: Path) -> None:
    """§8.6 rules 2 and 5."""
    src = _compiled(tmp_path).source
    for earlier, later in (
        ("  name:", "  description:"),
        ("  description:", "  domain:"),
        ("  domain:", "  input:"),
        ("  input:", "\ntriggers:"),
        ("\ntriggers:", "\nactions:"),
        ("\nactions:", "\nmode:"),
    ):
        assert src.index(earlier) < src.index(later), f"{earlier!r} must precede {later!r}"


def test_the_document_ends_with_exactly_one_newline_and_no_trailing_space(tmp_path: Path) -> None:
    """§8.6 rule 8."""
    src = _compiled(tmp_path).source
    assert src.endswith("\n")
    assert not src.endswith("\n\n")
    assert "\r" not in src
    assert not any(line != line.rstrip() for line in src.splitlines())


# --- determinism ------------------------------------------------------------


def test_compiling_the_same_bundle_twice_emits_identical_bytes(tmp_path: Path) -> None:
    """R8 / §8.6 — the whole point of a compiled artifact."""
    first = _compiled(tmp_path / "a").source
    second = _compiled(tmp_path / "b").source
    assert first == second


def test_the_emitted_yaml_expands_like_the_hand_written_equivalent(tmp_path: Path) -> None:
    """The artifact is not merely stable, it is the blueprint it claims to be."""
    obj = _compiled(tmp_path)
    expanded = parse_blueprint(obj.source, display_path=PATH).expand(
        {"switch_entity": "sensor.office_paddle", "room_light": "light.office"}
    )
    assert expanded["triggers"][0]["entity_id"] == "sensor.office_paddle"
    assert expanded["actions"][0]["target"]["entity_id"] == "light.office"
    # The optional input's declared default fills in.
    assert expanded["actions"][0]["data"]["brightness_step_pct"] == 10
