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
    raw_action({"action": "light.turn_on", "target": {"entity_id": ["light.hallway", "light.kitchen"]}})
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
