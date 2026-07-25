"""Decompile/adopt of group-helper objects into `helpers/` (root-level
layout), with compile(decompile(x)) == x round-trip byte-stability applied to
the config-entry options body.

`GroupHelperConfig` decompiles to the plain assignment call form (mirrors the
nine storage-collection helpers, `hassle.decompiler.codegen._helper_source`)
-- unlike template helpers, there is no Jinja `state=` field to
defer into a decorator body, so no decorator form exists for group at all.
There is no identity kwarg to rename -- `GroupHelperConfig` has no `id`/
`unique_id` field at all (docs/internals/ha-api-notes.md §38.1). Identity is derived
from `name` (slugified) at both compile and decompile time.

Nested groups (a group whose members are groups) decompile as PLAIN entity
references -- a member entity id renders as an ordinary string literal via
`render_literal`, never the `e.<domain>.<id>` cosmetic entity-reference form
-- `entities` list order preserved verbatim both directions.
"""

from __future__ import annotations

from pathlib import Path

from hassle.compiler.bundle import compile_bundle
from hassle.decompiler.codegen import decompile_object

FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "dsl"
    / "group_helper_declarations"
    / "bundle"
)


def test_decompile_group_cover_produces_matching_builder_call() -> None:
    result = compile_bundle(FIXTURE)
    key = "group_cover:entryway_top"
    obj = result.objects[key]
    source = decompile_object(key, obj)

    assert source.startswith("entryway_top = group_cover(")
    assert "name='Entryway Top'" in source
    assert "id=" not in source  # no identity kwarg at all (§38.1)
    assert "unique_id=" not in source
    assert "hide_members=False" in source


def test_decompile_group_light_includes_all_kwarg() -> None:
    result = compile_bundle(FIXTURE)
    key = "group_light:downstairs_lights"
    obj = result.objects[key]
    source = decompile_object(key, obj)
    assert "all=True" in source


def test_decompile_group_sensor_includes_type_kwarg() -> None:
    result = compile_bundle(FIXTURE)
    key = "group_sensor:average_temp"
    obj = result.objects[key]
    source = decompile_object(key, obj)
    assert "type='mean'" in source


def test_decompile_every_group_domain_uses_matching_builder_name() -> None:
    result = compile_bundle(FIXTURE)
    expected_builder = {
        "group_cover:entryway_top": "group_cover",
        "group_light:downstairs_lights": "group_light",
        "group_switch:outdoor_switches": "group_switch",
        "group_binary_sensor:any_door_open": "group_binary_sensor",
        "group_sensor:average_temp": "group_sensor",
        "group_button:all_doorbells": "group_button",
        "group_event:all_doorbell_events": "group_event",
        "group_fan:all_fans": "group_fan",
        "group_lock:all_locks": "group_lock",
        "group_media_player:whole_house_audio": "group_media_player",
        "group_notify:all_phones": "group_notify",
        "group_valve:irrigation_zone_a": "group_valve",
    }
    for key, builder in expected_builder.items():
        obj = result.objects[key]
        source = decompile_object(key, obj)
        assert f"= {builder}(" in source


def test_nested_group_member_decompiles_as_plain_string_not_entity_ref() -> None:
    # `group_cover:entryway_top`'s entities include `cover.bay_window_top`,
    # itself another group's entity id -- decompiles as a PLAIN literal, not
    # `e.cover.bay_window_top` (module docstring: "plain entity references").
    result = compile_bundle(FIXTURE)
    key = "group_cover:entryway_top"
    obj = result.objects[key]
    source = decompile_object(key, obj)
    assert "'cover.bay_window_top'" in source
    assert "e.cover.bay_window_top" not in source


def test_entities_list_order_preserved_verbatim() -> None:
    result = compile_bundle(FIXTURE)
    key = "group_cover:entryway_top"
    obj = result.objects[key]
    source = decompile_object(key, obj)
    idx_bay = source.index("cover.bay_window_top")
    idx_garage = source.index("cover.garage_door")
    assert idx_bay < idx_garage


def test_decompile_recompile_round_trip_is_byte_stable_for_options_body(tmp_path: Path) -> None:
    """Applied to a config-entry options body: compile(decompile(x)) == x."""
    result = compile_bundle(FIXTURE)
    original_ir = {key: obj.to_ha() for key, obj in result.objects.items()}

    lines = [
        "from hassle import (",
        "    group_binary_sensor,",
        "    group_button,",
        "    group_cover,",
        "    group_event,",
        "    group_fan,",
        "    group_light,",
        "    group_lock,",
        "    group_media_player,",
        "    group_notify,",
        "    group_sensor,",
        "    group_switch,",
        "    group_valve,",
        ")",
        "",
    ]
    for key, obj in sorted(result.objects.items()):
        lines.append(decompile_object(key, obj))
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "helpers.py").write_text("\n".join(lines), encoding="utf-8")

    recompiled = compile_bundle(bundle_dir)
    recompiled_ir = {key: obj.to_ha() for key, obj in recompiled.objects.items()}

    assert recompiled_ir == original_ir
