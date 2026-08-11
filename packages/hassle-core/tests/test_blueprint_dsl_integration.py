"""Stage 2 against the rest of the system (blueprints-design §8.7, §8.8, §8.9).

Three seams a DSL-authored blueprint has to meet:

- **§8.7** defining the same domain/path as both a DSL blueprint and an on-disk
  file is an error naming BOTH, not a silent precedence rule;
- **§8.8** the simulator prefers a compiled blueprint object from the same
  ``CompileResult`` over the on-disk lookup, so an instance of a blueprint that
  was never written to disk still expands;
- **§8.9** stage 1's instance checks work against a DSL declaration, and gain
  the one the declaration makes newly answerable — an entity-selector input
  handed something that is not an entity id.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hassle.compiler.blueprint_dsl import BlueprintDefinedTwiceError
from hassle.compiler.bundle import compile_bundle
from hassle.registry.finding import Finding
from hassle.registry.snapshot import RegistrySnapshot
from hassle.registry.validate import validate_bundle
from hassle.testing import Simulator
from hassle_dev.snapshots import check_snapshot, normalize_error

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures" / "registry" / "home.json"
SNAP_DIR_ERRORS = Path(__file__).resolve().parent / "snapshots" / "errors"
SNAP_DIR_FINDINGS = Path(__file__).resolve().parent / "snapshots" / "findings"

PATH = "local/room-switch-controls.yaml"

BLUEPRINT_DSL = '''\
"""A DSL-authored blueprint."""

from hassle import blueprint, bp_input, service, state, when


@blueprint(
    domain="automation",
    path="local/room-switch-controls.yaml",
    name="Room switch controls",
)
def room_switch_controls():
    switch_entity = bp_input(
        "switch_entity", selector={"entity": {"filter": [{"domain": "binary_sensor"}]}}
    )
    room_light = bp_input("room_light", selector={"entity": {"filter": [{"domain": "light"}]}})
    when(state(switch_entity).to("on"))
    service("light.turn_on", target={"entity_id": room_light})
'''

ON_DISK = """\
blueprint:
  name: Room switch controls
  domain: automation
  input:
    switch_entity:
mode: single
"""


@pytest.fixture(scope="module")
def snapshot() -> RegistrySnapshot:
    return RegistrySnapshot.load(FIXTURE)


def _instance(inputs: str) -> str:
    return (
        "from hassle import blueprint_automation\n"
        "blueprint_automation(\n"
        '    id="office_switch",\n'
        f'    use_blueprint="{PATH}",\n'
        f"    inputs={inputs},\n"
        ")\n"
    )


def _bundle(
    tmp_path: Path, *, dsl: str = BLUEPRINT_DSL, instance: str | None = None, on_disk: bool = False
) -> Path:
    root = tmp_path / "bundle"
    root.mkdir(parents=True, exist_ok=True)
    (root / "switches.py").write_text(dsl, encoding="utf-8")
    if instance is not None:
        (root / "misc.py").write_text(instance, encoding="utf-8")
    if on_disk:
        target = root / "blueprints" / "automation" / PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(ON_DISK, encoding="utf-8")
    return root


def _findings(tmp_path: Path, snapshot: RegistrySnapshot, instance: str) -> list[Finding]:
    return validate_bundle(compile_bundle(_bundle(tmp_path, instance=instance)), snapshot)


def _of(findings: list[Finding], code: str) -> list[Finding]:
    return [f for f in findings if f.code == code]


# --- §8.7: the same blueprint declared twice --------------------------------


def test_defining_a_blueprint_in_the_dsl_and_on_disk_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(BlueprintDefinedTwiceError):
        compile_bundle(_bundle(tmp_path, on_disk=True))


def test_defined_twice_message_names_both_sources(tmp_path: Path) -> None:
    with pytest.raises(BlueprintDefinedTwiceError) as excinfo:
        compile_bundle(_bundle(tmp_path, on_disk=True))
    message = str(excinfo.value)
    assert "switches.py" in message
    assert "blueprints/automation/local/room-switch-controls.yaml" in message


def test_defined_twice_message_snapshot(tmp_path: Path) -> None:
    with pytest.raises(BlueprintDefinedTwiceError) as excinfo:
        compile_bundle(_bundle(tmp_path, on_disk=True))
    check_snapshot(
        SNAP_DIR_ERRORS,
        "blueprint_defined_twice",
        normalize_error(str(excinfo.value), mask_lines_for="switches.py"),
    )


# --- §8.8: the simulator prefers the compiled object ------------------------


GOOD_INPUTS = '{"switch_entity": "binary_sensor.office_paddle", "room_light": "light.office"}'


def test_the_simulator_expands_an_instance_of_a_never_written_blueprint(
    tmp_path: Path,
) -> None:
    """There is no file on disk at all — only the compiled object.

    Asserted by RUNNING the instance, not by its mere presence: an unexpanded
    instance still appears in `automation_keys()` (it is a registered
    automation either way), so only firing its trigger and seeing the
    blueprint's own action distinguishes expansion from inertness.
    """
    compiled = compile_bundle(_bundle(tmp_path, instance=_instance(GOOD_INPUTS)))
    assert not (tmp_path / "bundle" / "blueprints").exists()
    sim = Simulator(compiled)
    assert "automation:office_switch" in sim.automation_keys()
    sim.state_change("binary_sensor.office_paddle", "off", "on")
    sim.assert_called("light.turn_on", entity_id="light.office")


def test_an_instance_of_an_absent_blueprint_stays_inert(tmp_path: Path) -> None:
    """§8.8: absent both, behavior is unchanged from today — inert, not an error."""
    root = tmp_path / "bundle"
    root.mkdir(parents=True, exist_ok=True)
    (root / "misc.py").write_text(_instance(GOOD_INPUTS), encoding="utf-8")
    Simulator(compile_bundle(root))  # must not raise


# --- §8.9: instance validation against a DSL declaration --------------------


def test_a_missing_required_input_is_found_against_a_dsl_blueprint(
    tmp_path: Path, snapshot: RegistrySnapshot
) -> None:
    findings = _findings(
        tmp_path, snapshot, _instance('{"switch_entity": "binary_sensor.office_paddle"}')
    )
    assert len(_of(findings, "blueprint-missing-input")) == 1


def test_an_unknown_input_is_found_against_a_dsl_blueprint(
    tmp_path: Path, snapshot: RegistrySnapshot
) -> None:
    findings = _findings(tmp_path, snapshot, _instance(f'{{**{GOOD_INPUTS}, "nope": 1}}'))
    assert len(_of(findings, "blueprint-unknown-input")) == 1


def test_a_dsl_blueprint_is_not_reported_as_missing_from_the_bundle(
    tmp_path: Path, snapshot: RegistrySnapshot
) -> None:
    """A compiled blueprint IS in the bundle — the §6.2 warning must not fire."""
    findings = _findings(tmp_path, snapshot, _instance(GOOD_INPUTS))
    assert _of(findings, "blueprint-not-in-bundle") == []


NOT_AN_ENTITY = '{"switch_entity": "binary_sensor.office_paddle", "room_light": "kitchen"}'


def test_an_entity_selector_given_a_non_entity_id_is_a_finding(
    tmp_path: Path, snapshot: RegistrySnapshot
) -> None:
    findings = _findings(tmp_path, snapshot, _instance(NOT_AN_ENTITY))
    assert len(_of(findings, "blueprint-input-not-an-entity-id")) == 1


def test_a_valid_entity_id_is_not_flagged(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    findings = _findings(tmp_path, snapshot, _instance(GOOD_INPUTS))
    assert _of(findings, "blueprint-input-not-an-entity-id") == []


def test_not_an_entity_id_message_snapshot(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    findings = _findings(tmp_path, snapshot, _instance(NOT_AN_ENTITY))
    check_snapshot(
        SNAP_DIR_FINDINGS,
        "blueprint_input_not_an_entity_id",
        normalize_error(
            str(_of(findings, "blueprint-input-not-an-entity-id")[0]), mask_lines_for="misc.py"
        ),
    )
