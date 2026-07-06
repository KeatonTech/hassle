"""``ux/dsl-ergonomics``, item 3 -- bare entity target sugar.

`service(..., target=e.weather.forecast_home)` (an `EntityRef`/`str`, or a list of
them) compiles to `target={"entity_id": ...}` identically; `area()`/`floor()`/
`label()`/`device_id()` target helper objects are also accepted directly as
`target=`. The decompiler emits the bare form when a stored target dict has
exactly one key -- `entity_id` (single ref or list) or one of the four id-key
forms -- and keeps the plain dict literal for any multi-key target.
"""

from __future__ import annotations

from hassle.compiler.bundle import compile_bundle
from hassle.decompiler.codegen import decompile_bundle
from hassle.ir.canonical import sha256_hash
from hassle.ir.models import parse


def _write_bundle(tmp_path, source: str) -> str:
    (tmp_path / "objects.py").write_text(source, encoding="utf-8")
    return str(tmp_path)


def test_bare_entity_ref_target_compiles_to_entity_id_dict(tmp_path) -> None:
    source = (
        "from hassle import automation, service\n"
        "from hassle.registry import entities as e\n\n\n"
        '@automation(id="a1", alias="A1")\n'
        "def a1():\n"
        '    service("weather.get_forecasts", target=e.weather.forecast_home)\n'
    )
    result = compile_bundle(_write_bundle(tmp_path, source))
    (obj,) = result.objects.values()
    action = obj.to_ha()["actions"][0]
    assert action["target"] == {"entity_id": "weather.forecast_home"}


def test_bare_string_target_compiles_to_entity_id_dict(tmp_path) -> None:
    source = (
        "from hassle import automation, service\n\n\n"
        '@automation(id="a1", alias="A1")\n'
        "def a1():\n"
        '    service("light.turn_on", target="light.hallway")\n'
    )
    result = compile_bundle(_write_bundle(tmp_path, source))
    (obj,) = result.objects.values()
    action = obj.to_ha()["actions"][0]
    assert action["target"] == {"entity_id": "light.hallway"}


def test_list_of_entity_refs_target_compiles_to_entity_id_list(tmp_path) -> None:
    source = (
        "from hassle import automation, service\n"
        "from hassle.registry import entities as e\n\n\n"
        '@automation(id="a1", alias="A1")\n'
        "def a1():\n"
        '    service("light.turn_on", target=[e.light.a, e.light.b])\n'
    )
    result = compile_bundle(_write_bundle(tmp_path, source))
    (obj,) = result.objects.values()
    action = obj.to_ha()["actions"][0]
    assert action["target"] == {"entity_id": ["light.a", "light.b"]}


def test_area_floor_label_device_id_target_helpers(tmp_path) -> None:
    source = (
        "from hassle import area, automation, device_id, floor, label, service\n\n\n"
        '@automation(id="a1", alias="A1")\n'
        "def a1():\n"
        '    service("light.turn_on", target=area("office"))\n'
        '    service("light.turn_off", target=floor("upstairs"))\n'
        '    service("light.toggle", target=label("security"))\n'
        '    service("light.turn_on", target=device_id("dev123"))\n'
    )
    result = compile_bundle(_write_bundle(tmp_path, source))
    (obj,) = result.objects.values()
    actions = obj.to_ha()["actions"]
    assert actions[0]["target"] == {"area_id": "office"}
    assert actions[1]["target"] == {"floor_id": "upstairs"}
    assert actions[2]["target"] == {"label_id": "security"}
    assert actions[3]["target"] == {"device_id": "dev123"}


def test_dict_target_still_passes_through_unchanged(tmp_path) -> None:
    """The pre-existing dict form must be completely unaffected."""
    source = (
        "from hassle import automation, service\n\n\n"
        '@automation(id="a1", alias="A1")\n'
        "def a1():\n"
        '    service("light.turn_on", target={"entity_id": "light.hallway", "device_id": "d1"})\n'
    )
    result = compile_bundle(_write_bundle(tmp_path, source))
    (obj,) = result.objects.values()
    action = obj.to_ha()["actions"][0]
    assert action["target"] == {"entity_id": "light.hallway", "device_id": "d1"}


def test_no_target_still_omits_the_field(tmp_path) -> None:
    source = (
        "from hassle import automation, service\n\n\n"
        '@automation(id="a1", alias="A1")\n'
        "def a1():\n"
        '    service("light.turn_on")\n'
    )
    result = compile_bundle(_write_bundle(tmp_path, source))
    (obj,) = result.objects.values()
    action = obj.to_ha()["actions"][0]
    assert "target" not in action


def test_decompiler_emits_bare_form_for_single_entity_id_key() -> None:
    config = {
        "id": "a1",
        "alias": "A1",
        "triggers": [],
        "conditions": [],
        "actions": [
            {"action": "light.turn_on", "target": {"entity_id": "light.hallway"}},
        ],
    }
    obj = parse(config, kind="automation")
    source = decompile_bundle({obj.object_key(): obj})
    assert "target=e.light.hallway" in source


def test_decompiler_emits_bare_form_for_entity_id_list() -> None:
    config = {
        "id": "a1",
        "alias": "A1",
        "triggers": [],
        "conditions": [],
        "actions": [
            {"action": "light.turn_on", "target": {"entity_id": ["light.a", "light.b"]}},
        ],
    }
    obj = parse(config, kind="automation")
    source = decompile_bundle({obj.object_key(): obj})
    assert "target=[e.light.a, e.light.b]" in source


def test_decompiler_emits_area_floor_label_device_id_calls() -> None:
    config = {
        "id": "a1",
        "alias": "A1",
        "triggers": [],
        "conditions": [],
        "actions": [
            {"action": "light.turn_on", "target": {"area_id": "office"}},
            {"action": "light.turn_off", "target": {"floor_id": "upstairs"}},
            {"action": "light.toggle", "target": {"label_id": "security"}},
            {"action": "light.turn_on", "target": {"device_id": "dev123"}},
        ],
    }
    obj = parse(config, kind="automation")
    source = decompile_bundle({obj.object_key(): obj})
    assert 'target=area("office")' in source
    assert 'target=floor("upstairs")' in source
    assert 'target=label("security")' in source
    assert 'target=device_id("dev123")' in source


def test_decompiler_keeps_dict_form_for_multi_key_target() -> None:
    """A multi-key target (e.g. entity_id + device_id together) is never
    collapsed to the bare sugar -- it keeps the plain dict literal."""
    config = {
        "id": "a1",
        "alias": "A1",
        "triggers": [],
        "conditions": [],
        "actions": [
            {
                "action": "light.turn_on",
                "target": {"entity_id": "light.hallway", "device_id": "d1"},
            },
        ],
    }
    obj = parse(config, kind="automation")
    source = decompile_bundle({obj.object_key(): obj})
    # Multi-key target keeps the plain dict literal; entity_id nested inside
    # still gets the entity-ref sugar (pre-existing DESIGN §7.3 behavior).
    assert 'target={"entity_id": e.light.hallway, "device_id": "d1"}' in source


def test_target_sugar_roundtrips_byte_identical(tmp_path) -> None:
    config = {
        "id": "a1",
        "alias": "A1",
        "triggers": [],
        "conditions": [],
        "actions": [
            {"action": "light.turn_on", "target": {"entity_id": "light.hallway"}},
            {"action": "light.turn_on", "target": {"entity_id": ["light.a", "light.b"]}},
            {"action": "light.turn_on", "target": {"area_id": "office"}},
        ],
    }
    obj = parse(config, kind="automation")
    source = decompile_bundle({obj.object_key(): obj})
    bundle_dir = _write_bundle(tmp_path, source)
    result = compile_bundle(bundle_dir)
    (recompiled,) = result.objects.values()
    assert sha256_hash(recompiled.to_ha()) == sha256_hash(obj.to_ha())
