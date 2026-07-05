"""M3: entity/target reference extraction from compiled IR (DESIGN §9 tier 2).

Reaches every position DESIGN and the milestone call out: classic trigger/
condition/action `entity_id` (bare string and list forms), purpose-trigger
`target:` blocks (all five keys), Jinja template strings, and `raw_*` blocks.

Uses `hassle.compiler.bundle.compile_bundle` against small inline bundles
written to a tmp_path (no network; pure local files) plus a few of the
existing M1 golden bundles that already exercise these shapes.
"""

from __future__ import annotations

from pathlib import Path

from hassle.compiler.bundle import compile_bundle
from hassle.registry.extract import extract_references

REPO_ROOT = Path(__file__).resolve().parents[3]


def _write_bundle(tmp_path: Path, code: str) -> Path:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "automation.py").write_text(code, encoding="utf-8")
    return bundle


def test_extract_classic_trigger_entity_id_bare_string(tmp_path: Path) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, service, state, when

@automation(id="a", alias="A")
def a():
    when(state("binary_sensor.trigger").to("on"))
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
    )
    result = compile_bundle(bundle)
    refs = extract_references(result)
    entity_ids = {r.entity_id for r in refs if r.entity_id is not None}
    assert "binary_sensor.trigger" in entity_ids
    assert "light.hallway" in entity_ids


def test_extract_entity_id_list_form(tmp_path: Path) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, raw_action, raw_trigger

@automation(id="a", alias="A")
def a():
    raw_trigger({"trigger": "state", "entity_id": ["binary_sensor.a", "binary_sensor.b"]})
    raw_action({
        "action": "light.turn_on",
        "target": {"entity_id": ["light.hallway", "light.kitchen"]},
    })
""",
    )
    result = compile_bundle(bundle)
    refs = extract_references(result)
    entity_ids = {r.entity_id for r in refs if r.entity_id is not None}
    assert {"binary_sensor.a", "binary_sensor.b", "light.hallway", "light.kitchen"} <= entity_ids


def test_extract_purpose_trigger_target_all_five_keys(tmp_path: Path) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import (
    automation, area, device_id, floor, label, met, on, only_if, service, when,
)

@automation(id="a", alias="A")
def a():
    when(on("motion.detected", target=area("office")))
    when(on("motion.detected", target=floor("upstairs")))
    when(on("motion.detected", target=label("security")))
    when(on("motion.detected", target=device_id("device_light_1")))
    when(on("motion.detected", target="sensor.wireless_device_battery"))
    only_if(met("climate.is_target_temperature", target=area("office")))
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
    )
    result = compile_bundle(bundle)
    refs = extract_references(result)
    area_ids = {r.area_id for r in refs if r.area_id is not None}
    floor_ids = {r.floor_id for r in refs if r.floor_id is not None}
    label_ids = {r.label_id for r in refs if r.label_id is not None}
    device_ids = {r.device_id for r in refs if r.device_id is not None}
    entity_ids = {r.entity_id for r in refs if r.entity_id is not None}
    assert "office" in area_ids
    assert "upstairs" in floor_ids
    assert "security" in label_ids
    assert "device_light_1" in device_ids
    assert "sensor.wireless_device_battery" in entity_ids


def test_extract_purpose_trigger_target_list_forms(tmp_path: Path) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, raw_trigger, service

@automation(id="a", alias="A")
def a():
    raw_trigger({
        "trigger": "motion.detected",
        "target": {"area_id": ["office", "kitchen"]},
    })
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
    )
    result = compile_bundle(bundle)
    refs = extract_references(result)
    area_ids = {r.area_id for r in refs if r.area_id is not None}
    assert {"office", "kitchen"} <= area_ids


def test_extract_entity_ids_inside_jinja_template_string(tmp_path: Path) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, service, template, when

@automation(id="a", alias="A")
def a():
    when(template("{{ states('binary_sensor.trigger') == 'on' }}"))
    service(
        "notify.mobile_app",
        message=template(
            "{{ state_attr('light.hallway', 'brightness') }} and "
            "{{ is_state('switch.kitchen_outlet', 'on') }}"
        ),
    )
""",
    )
    result = compile_bundle(bundle)
    refs = extract_references(result)
    entity_ids = {r.entity_id for r in refs if r.entity_id is not None}
    assert "binary_sensor.trigger" in entity_ids
    assert "light.hallway" in entity_ids
    assert "switch.kitchen_outlet" in entity_ids


def test_extract_entity_ids_inside_raw_block(tmp_path: Path) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, raw_action, raw_condition, raw_trigger

@automation(id="a", alias="A")
def a():
    raw_trigger({"platform": "device", "device_id": "device_light_1", "type": "turned_on"})
    raw_condition({"condition": "state", "entity_id": "input_boolean.guest_mode", "state": "on"})
    raw_action({"service": "light.turn_on", "entity_id": "light.hallway"})
""",
    )
    result = compile_bundle(bundle)
    refs = extract_references(result)
    entity_ids = {r.entity_id for r in refs if r.entity_id is not None}
    device_ids = {r.device_id for r in refs if r.device_id is not None}
    assert "input_boolean.guest_mode" in entity_ids
    assert "light.hallway" in entity_ids
    assert "device_light_1" in device_ids


def test_extract_from_kitchen_sink_golden_has_spans() -> None:
    bundle = REPO_ROOT / "fixtures" / "dsl" / "kitchen_sink_full" / "bundle"
    result = compile_bundle(bundle)
    refs = extract_references(result)
    assert len(refs) > 0
    # every extracted reference must carry enough to point back at a DSL line
    # (span may be None only for a handful of prebuilt/helper cases; most must
    # have one so validation Findings can carry file:line, milestone item 7).
    with_span = [r for r in refs if r.span is not None]
    assert len(with_span) > 0


# --- reviewer B1: recursive descent into nested action containers ----------
# extract_references must reach entity/target references nested inside
# if_then/else_then, choose branches + default, repeat, parallel, and
# wait_for_trigger's inner trigger blocks -- not just the top-level
# trigger/condition/action lists.


def test_extract_reaches_if_then_else_branches(tmp_path: Path) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, else_then, if_then, service, state, when

@automation(id="a", alias="A")
def a():
    when(state("binary_sensor.trigger").to("on"))
    with if_then(state("sensor.temperature").is_("hot")):
        service("light.turn_on", target={"entity_id": "light.if_branch_entity"})
    with else_then():
        service("light.turn_on", target={"entity_id": "light.else_branch_entity"})
""",
    )
    result = compile_bundle(bundle)
    refs = extract_references(result)
    entity_ids = {r.entity_id for r in refs if r.entity_id is not None}
    assert "light.if_branch_entity" in entity_ids
    assert "light.else_branch_entity" in entity_ids


def test_extract_reaches_choose_branch_and_default(tmp_path: Path) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, choose, service, state, when

@automation(id="a", alias="A")
def a():
    when(state("binary_sensor.trigger").to("on"))
    with choose() as c:
        with c.when_(state("input_select.house_mode").is_("night")):
            service("light.turn_on", target={"entity_id": "light.choose_branch_entity"})
        with c.default():
            service("light.turn_on", target={"entity_id": "light.choose_default_entity"})
""",
    )
    result = compile_bundle(bundle)
    refs = extract_references(result)
    entity_ids = {r.entity_id for r in refs if r.entity_id is not None}
    assert "light.choose_branch_entity" in entity_ids
    assert "light.choose_default_entity" in entity_ids


def test_extract_reaches_repeat_sequence(tmp_path: Path) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, repeat_count, service, state, when

@automation(id="a", alias="A")
def a():
    when(state("binary_sensor.trigger").to("on"))
    with repeat_count(2):
        service("light.turn_on", target={"entity_id": "light.repeat_body_entity"})
""",
    )
    result = compile_bundle(bundle)
    refs = extract_references(result)
    entity_ids = {r.entity_id for r in refs if r.entity_id is not None}
    assert "light.repeat_body_entity" in entity_ids


def test_extract_reaches_parallel_sequence(tmp_path: Path) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, parallel, service, state, when

@automation(id="a", alias="A")
def a():
    when(state("binary_sensor.trigger").to("on"))
    with parallel():
        service("light.turn_on", target={"entity_id": "light.parallel_body_entity"})
""",
    )
    result = compile_bundle(bundle)
    refs = extract_references(result)
    entity_ids = {r.entity_id for r in refs if r.entity_id is not None}
    assert "light.parallel_body_entity" in entity_ids


def test_extract_reaches_nested_repeat_inside_choose(tmp_path: Path) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, choose, repeat_count, service, state, when

@automation(id="a", alias="A")
def a():
    when(state("binary_sensor.trigger").to("on"))
    with choose() as c:
        with c.when_(state("input_boolean.armed").is_("on")):
            with repeat_count(2):
                service("light.turn_on", target={"entity_id": "light.nested_nested_entity"})
""",
    )
    result = compile_bundle(bundle)
    refs = extract_references(result)
    entity_ids = {r.entity_id for r in refs if r.entity_id is not None}
    assert "light.nested_nested_entity" in entity_ids


def test_extract_reaches_wait_for_trigger_inner_trigger(tmp_path: Path) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, service, state, wait_for, when

@automation(id="a", alias="A")
def a():
    when(state("binary_sensor.trigger").to("on"))
    wait_for(state("binary_sensor.wait_for_inner_entity").to("off"))
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
    )
    result = compile_bundle(bundle)
    refs = extract_references(result)
    entity_ids = {r.entity_id for r in refs if r.entity_id is not None}
    assert "binary_sensor.wait_for_inner_entity" in entity_ids


def test_device_block_registry_uuid_entity_id_not_validated_as_entity_name(tmp_path) -> None:
    # Modern HA device triggers/actions store ENTITY REGISTRY UUIDs (32-hex) in
    # their entity_id field, not domain.object_id names (owner field evidence:
    # `d457ce94e8ab259e6867b4fc918d1106` flagged as unknown-entity). Those must
    # not be validated as entity names.
    from hassle.compiler.bundle import compile_bundle
    from hassle.registry.snapshot import RegistrySnapshot
    from hassle.registry.validate import validate_bundle

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "a.py").write_text(
        "from hassle import automation, when, raw_trigger, raw_action\n"
        "@automation(id='x', alias='X')\n"
        "def x():\n"
        "    when(raw_trigger({\n"
        "        'trigger': 'device',\n"
        "        'device_id': 'aaaabbbbccccdddd1111222233334444',\n"
        "        'entity_id': 'd457ce94e8ab259e6867b4fc918d1106',\n"
        "        'domain': 'binary_sensor', 'type': 'opened',\n"
        "    }))\n"
        "    raw_action({\n"
        "        'device_id': 'aaaabbbbccccdddd1111222233334444',\n"
        "        'entity_id': 'd457ce94e8ab259e6867b4fc918d1106',\n"
        "        'domain': 'lock', 'type': 'lock',\n"
        "    })\n",
        encoding="utf-8",
    )
    result = compile_bundle(bundle)
    snapshot = RegistrySnapshot.model_validate(
        {
            "entities": [{"entity_id": "light.known", "name": "K"}],
            "devices": [{"id": "aaaabbbbccccdddd1111222233334444", "name": "Lock"}],
        }
    )
    findings = validate_bundle(result, snapshot)
    assert not [f for f in findings if f.code == "unknown-entity"], findings
