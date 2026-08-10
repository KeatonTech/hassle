"""`hassle validate`'s blueprint rules (blueprints-design §6), offline.

Three rules, each motivated by a real Home Assistant rejection rather than by
a schema guess (§6.4 makes that the standing bar for adding a fourth):

1. **Instance inputs** — an instance whose `use_blueprint` path matches a
   bundle-local blueprint is checked against its declared `blueprint.input`:
   a missing required input or an unknown input name is a finding. Exactly
   the class HA rejects with an opaque 400 at push time.
2. **Unmanaged blueprint** — an instance referencing a path with no
   bundle-local file is a WARNING, not an error: it may legitimately be a
   community blueprint living only in HA. The message names the file that
   would make it managed.
3. **The empty-optional-entity rule**, from the field 400: an optional
   entity-selector input (`default: ""`) appearing as a literal
   `target.entity_id` / `entity_id` anywhere in the blueprint body. HA
   validates the STATIC expanded config and rejects a literal empty id even
   inside a runtime-guarded branch.

All three messages are product surface: what / where / fix, snapshot-tested.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hassle.compiler.bundle import compile_bundle
from hassle.registry.finding import Finding
from hassle.registry.snapshot import RegistrySnapshot
from hassle.registry.validate import validate_bundle
from hassle_dev.snapshots import check_snapshot, normalize_error

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE = REPO_ROOT / "fixtures" / "registry" / "home.json"
SNAP_DIR = Path(__file__).resolve().parent / "snapshots" / "findings"

BLUEPRINT = """\
blueprint:
  name: Room Switch Controls
  domain: automation
  input:
    switch_entity:
      name: Switch
      selector:
        entity:
          filter:
            - domain: light
    room_light:
      name: Room light
      selector:
        entity:
          filter:
            - domain: light
    dim_step_pct:
      name: Dim step
      default: 10
mode: restart
triggers:
  - trigger: state
    entity_id: !input switch_entity
actions:
  - action: light.turn_on
    target:
      entity_id: !input room_light
    data:
      brightness_step_pct: !input dim_step_pct
"""

PATH = "local/room-switch-controls.yaml"


@pytest.fixture(scope="module")
def snapshot() -> RegistrySnapshot:
    return RegistrySnapshot.load(FIXTURE)


def _bundle(tmp_path: Path, *, dsl: str, blueprints: dict[str, str] | None = None) -> Path:
    root = tmp_path / "bundle"
    root.mkdir(exist_ok=True)
    (root / "misc.py").write_text(dsl, encoding="utf-8")
    for rel, text in (blueprints or {}).items():
        target = root / "blueprints" / "automation" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


def _instance(inputs: str, *, path: str = PATH) -> str:
    return (
        "from hassle import blueprint_automation\n"
        "blueprint_automation(\n"
        '    id="office_switch",\n'
        f'    use_blueprint="{path}",\n'
        f"    inputs={inputs},\n"
        ")\n"
    )


def _findings(tmp_path: Path, snapshot: RegistrySnapshot, **kwargs: object) -> list[Finding]:
    return validate_bundle(compile_bundle(_bundle(tmp_path, **kwargs)), snapshot)  # type: ignore[arg-type]


def _of(findings: list[Finding], code: str) -> list[Finding]:
    return [f for f in findings if f.code == code]


def _normalize(msg: str) -> str:
    return normalize_error(msg, mask_lines_for="misc.py")


# --- rule 1: an instance's inputs are checked against the blueprint --------


GOOD_INPUTS = '{"switch_entity": "light.hallway", "room_light": "light.hallway"}'


def test_a_well_formed_instance_produces_no_blueprint_findings(
    tmp_path: Path, snapshot: RegistrySnapshot
) -> None:
    findings = _findings(
        tmp_path, snapshot, dsl=_instance(GOOD_INPUTS), blueprints={PATH: BLUEPRINT}
    )
    assert [f for f in findings if f.code.startswith("blueprint-")] == []


def test_a_missing_required_input_is_a_finding(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    findings = _findings(
        tmp_path,
        snapshot,
        dsl=_instance('{"switch_entity": "light.hallway"}'),
        blueprints={PATH: BLUEPRINT},
    )
    matches = _of(findings, "blueprint-missing-input")
    assert len(matches) == 1
    assert "room_light" in matches[0].message


def test_an_optional_input_may_be_omitted(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    """`dim_step_pct` has a `default:`, so leaving it out is correct usage,
    not a finding."""
    findings = _findings(
        tmp_path, snapshot, dsl=_instance(GOOD_INPUTS), blueprints={PATH: BLUEPRINT}
    )
    assert _of(findings, "blueprint-missing-input") == []


def test_an_unknown_input_name_is_a_finding(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    findings = _findings(
        tmp_path,
        snapshot,
        dsl=_instance(
            '{"switch_entity": "light.hallway", "room_light": "light.hallway",'
            ' "romo_light": "light.hallway"}'
        ),
        blueprints={PATH: BLUEPRINT},
    )
    matches = _of(findings, "blueprint-unknown-input")
    assert len(matches) == 1
    assert "romo_light" in matches[0].message


def test_an_unknown_input_gets_a_did_you_mean(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    findings = _findings(
        tmp_path,
        snapshot,
        dsl=_instance(
            '{"switch_entity": "light.hallway", "room_light": "light.hallway",'
            ' "romo_light": "light.hallway"}'
        ),
        blueprints={PATH: BLUEPRINT},
    )
    assert "room_light" in _of(findings, "blueprint-unknown-input")[0].fix


def test_input_findings_point_at_the_instance(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    """Where: the DSL declaration site, not the blueprint file -- the instance
    is what the author has to change."""
    findings = _findings(
        tmp_path,
        snapshot,
        dsl=_instance('{"switch_entity": "light.hallway"}'),
        blueprints={PATH: BLUEPRINT},
    )
    finding = _of(findings, "blueprint-missing-input")[0]
    assert finding.file is not None and finding.file.endswith("misc.py")
    assert finding.line is not None


def test_missing_input_message_snapshot(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    findings = _findings(
        tmp_path,
        snapshot,
        dsl=_instance('{"switch_entity": "light.hallway"}'),
        blueprints={PATH: BLUEPRINT},
    )
    check_snapshot(
        SNAP_DIR,
        "blueprint_missing_input",
        _normalize(str(_of(findings, "blueprint-missing-input")[0])),
    )


def test_unknown_input_message_snapshot(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    findings = _findings(
        tmp_path,
        snapshot,
        dsl=_instance(
            '{"switch_entity": "light.hallway", "room_light": "light.hallway",'
            ' "romo_light": "light.hallway"}'
        ),
        blueprints={PATH: BLUEPRINT},
    )
    check_snapshot(
        SNAP_DIR,
        "blueprint_unknown_input",
        _normalize(str(_of(findings, "blueprint-unknown-input")[0])),
    )


# --- rule 2: an instance with no bundle-local blueprint --------------------


def test_an_unmanaged_blueprint_is_a_warning(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    """A community blueprint that lives only in HA is legitimate -- e.g. the
    jay-kub tap-sequences instances -- so this is a warning, never an error."""
    findings = _findings(tmp_path, snapshot, dsl=_instance("{}", path="jay-kub/taps.yaml"))
    matches = _of(findings, "blueprint-not-in-bundle")
    assert len(matches) == 1
    assert matches[0].severity == "warning"


def test_the_unmanaged_warning_names_the_file_that_would_manage_it(
    tmp_path: Path, snapshot: RegistrySnapshot
) -> None:
    findings = _findings(tmp_path, snapshot, dsl=_instance("{}", path="jay-kub/taps.yaml"))
    assert (
        "blueprints/automation/jay-kub/taps.yaml" in _of(findings, "blueprint-not-in-bundle")[0].fix
    )


def test_an_unmanaged_blueprints_inputs_are_not_checked(
    tmp_path: Path, snapshot: RegistrySnapshot
) -> None:
    """There is nothing to check against -- and guessing would produce a
    finding the author cannot act on."""
    findings = _findings(tmp_path, snapshot, dsl=_instance("{}", path="jay-kub/taps.yaml"))
    assert _of(findings, "blueprint-missing-input") == []
    assert _of(findings, "blueprint-unknown-input") == []


def test_a_managed_blueprint_produces_no_unmanaged_warning(
    tmp_path: Path, snapshot: RegistrySnapshot
) -> None:
    findings = _findings(
        tmp_path, snapshot, dsl=_instance(GOOD_INPUTS), blueprints={PATH: BLUEPRINT}
    )
    assert _of(findings, "blueprint-not-in-bundle") == []


def test_unmanaged_message_snapshot(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    findings = _findings(tmp_path, snapshot, dsl=_instance("{}", path="jay-kub/taps.yaml"))
    check_snapshot(
        SNAP_DIR,
        "blueprint_not_in_bundle",
        _normalize(str(_of(findings, "blueprint-not-in-bundle")[0])),
    )


# --- rule 3: the empty-optional-entity rule (the field 400) ----------------


EMPTY_OPTIONAL = """\
blueprint:
  name: Bad
  domain: automation
  input:
    lights_pause_boolean:
      name: Lights pause
      default: ""
      selector:
        entity:
          filter:
            - domain: input_boolean
triggers: []
actions:
  - if:
      - condition: template
        value_template: "{{ lights_pause_boolean != '' }}"
    then:
      - action: input_boolean.turn_on
        target:
          entity_id: !input lights_pause_boolean
"""


def test_an_empty_optional_entity_input_used_literally_is_a_finding(
    tmp_path: Path, snapshot: RegistrySnapshot
) -> None:
    findings = _findings(
        tmp_path,
        snapshot,
        dsl=_instance("{}", path="local/bad.yaml"),
        blueprints={"local/bad.yaml": EMPTY_OPTIONAL},
    )
    matches = _of(findings, "blueprint-empty-optional-entity")
    assert len(matches) == 1
    assert "lights_pause_boolean" in matches[0].message


def test_the_runtime_guard_does_not_excuse_it(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    """The whole point of the rule: HA validates the STATIC expanded config,
    so the `if` above makes no difference at save time. (The fixture's action
    is already inside a guard -- this test names why that isn't enough.)"""
    findings = _findings(
        tmp_path,
        snapshot,
        dsl=_instance("{}", path="local/bad.yaml"),
        blueprints={"local/bad.yaml": EMPTY_OPTIONAL},
    )
    assert _of(findings, "blueprint-empty-optional-entity")


def test_the_finding_prescribes_the_templated_target_fix(
    tmp_path: Path, snapshot: RegistrySnapshot
) -> None:
    """§6.3: "The fix the finding prescribes: bind the input to a variable and
    use a templated target"."""
    findings = _findings(
        tmp_path,
        snapshot,
        dsl=_instance("{}", path="local/bad.yaml"),
        blueprints={"local/bad.yaml": EMPTY_OPTIONAL},
    )
    fix = _of(findings, "blueprint-empty-optional-entity")[0].fix
    assert "variables:" in fix
    assert "{{ lights_pause_boolean }}" in fix
    assert "blueprints-design.md" in fix


def test_the_templated_target_form_is_clean(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    """The worked example from §6.3, which is what the BrandtCamp blueprint
    actually does -- the shape the finding tells you to write must not itself
    be flagged."""
    fixed = EMPTY_OPTIONAL.replace(
        "          entity_id: !input lights_pause_boolean",
        '          entity_id: "{{ lights_pause_boolean }}"',
    ).replace(
        "actions:\n",
        "actions:\n  - variables:\n      lights_pause_boolean: !input lights_pause_boolean\n",
    )
    findings = _findings(
        tmp_path,
        snapshot,
        dsl=_instance("{}", path="local/bad.yaml"),
        blueprints={"local/bad.yaml": fixed},
    )
    assert _of(findings, "blueprint-empty-optional-entity") == []


def test_a_required_entity_input_used_literally_is_fine(
    tmp_path: Path, snapshot: RegistrySnapshot
) -> None:
    """The rule is about `default: ""`. A REQUIRED entity input can never
    expand to an empty string, so a literal target is correct and idiomatic --
    flagging it would make every blueprint in existence noisy."""
    findings = _findings(
        tmp_path, snapshot, dsl=_instance(GOOD_INPUTS), blueprints={PATH: BLUEPRINT}
    )
    assert _of(findings, "blueprint-empty-optional-entity") == []


def test_an_empty_list_default_is_exempt(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    """`default: []` is the OPPOSITE of the bug: it is the one way a state
    trigger can say "no entity" without failing to load, and the BrandtCamp
    blueprint's `mode_boolean` relies on it. The rule keys on `default: ""`
    exactly, as §6.3 states."""
    list_default = EMPTY_OPTIONAL.replace('default: ""', "default: []").replace(
        "          filter:\n            - domain: input_boolean",
        "          multiple: true\n          filter:\n            - domain: input_boolean",
    )
    findings = _findings(
        tmp_path,
        snapshot,
        dsl=_instance("{}", path="local/bad.yaml"),
        blueprints={"local/bad.yaml": list_default},
    )
    assert _of(findings, "blueprint-empty-optional-entity") == []


def test_a_non_entity_selector_with_an_empty_default_is_exempt(
    tmp_path: Path, snapshot: RegistrySnapshot
) -> None:
    """§6.3 scopes the rule to an *entity-selector* input. A `text:` input
    defaulting to `""` (BrandtCamp's `tap_base`) is a value, not an entity
    reference, and never lands in an `entity_id` position."""
    text_default = EMPTY_OPTIONAL.replace(
        "      selector:\n        entity:\n          filter:\n            - domain: input_boolean",
        "      selector:\n        text:",
    )
    findings = _findings(
        tmp_path,
        snapshot,
        dsl=_instance("{}", path="local/bad.yaml"),
        blueprints={"local/bad.yaml": text_default},
    )
    assert _of(findings, "blueprint-empty-optional-entity") == []


def test_the_finding_points_at_the_blueprint_file(
    tmp_path: Path, snapshot: RegistrySnapshot
) -> None:
    """Where: this one is the BLUEPRINT's bug, not the instance's -- every
    instance would hit it."""
    findings = _findings(
        tmp_path,
        snapshot,
        dsl=_instance("{}", path="local/bad.yaml"),
        blueprints={"local/bad.yaml": EMPTY_OPTIONAL},
    )
    finding = _of(findings, "blueprint-empty-optional-entity")[0]
    assert finding.file == "blueprints/automation/local/bad.yaml"


def test_it_is_reported_once_per_input_not_once_per_instance(
    tmp_path: Path, snapshot: RegistrySnapshot
) -> None:
    """17 instances of one blueprint must not produce 17 copies of the same
    blueprint-level finding."""
    dsl = (
        "from hassle import blueprint_automation\n"
        "for i in range(3):\n"
        "    blueprint_automation(\n"
        '        id=f"switch_{i}",\n'
        '        use_blueprint="local/bad.yaml",\n'
        "        inputs={},\n"
        "    )\n"
    )
    findings = _findings(tmp_path, snapshot, dsl=dsl, blueprints={"local/bad.yaml": EMPTY_OPTIONAL})
    assert len(_of(findings, "blueprint-empty-optional-entity")) == 1


def test_a_bare_entity_id_counts_too(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    """§6.3 names `target.entity_id` / `entity_id` -- HA's legacy shorthand
    puts it directly on the action."""
    bare = EMPTY_OPTIONAL.replace(
        "        target:\n          entity_id: !input lights_pause_boolean",
        "        entity_id: !input lights_pause_boolean",
    )
    findings = _findings(
        tmp_path,
        snapshot,
        dsl=_instance("{}", path="local/bad.yaml"),
        blueprints={"local/bad.yaml": bare},
    )
    assert _of(findings, "blueprint-empty-optional-entity")


def test_an_entity_id_list_counts_too(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    listed = EMPTY_OPTIONAL.replace(
        "          entity_id: !input lights_pause_boolean",
        "          entity_id:\n            - !input lights_pause_boolean",
    )
    findings = _findings(
        tmp_path,
        snapshot,
        dsl=_instance("{}", path="local/bad.yaml"),
        blueprints={"local/bad.yaml": listed},
    )
    assert _of(findings, "blueprint-empty-optional-entity")


def test_empty_optional_entity_message_snapshot(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    findings = _findings(
        tmp_path,
        snapshot,
        dsl=_instance("{}", path="local/bad.yaml"),
        blueprints={"local/bad.yaml": EMPTY_OPTIONAL},
    )
    check_snapshot(
        SNAP_DIR,
        "blueprint_empty_optional_entity",
        _normalize(str(_of(findings, "blueprint-empty-optional-entity")[0])),
    )
