"""Decompiler codegen UX (owner feedback after first real pull, DESIGN §7.3).

Four output-style changes, all cosmetic (I3-preserving -- compiled IR must stay
byte-identical; `EntityRef` is a `str` subclass so `e.<domain>.<object_id>`
compiles to the exact same string as the quoted literal it replaces):

1. Function names derive from `alias` (slugified), not from `id` -- DESIGN §7.3
   as originally written. Collisions get deterministic `_2`/`_3` suffixes.
   No alias -> fall back to `automation_<id>` / `script_<id>`. Helpers keep
   their id-derived variable name (unaffected).
2. Entity ids in entity positions (state()/numeric_state() entity args, target
   entity_id values -- incl. nested in dicts, wait_for_trigger triggers, helper
   refs) emit `e.<domain>.<object_id>` (or `e.<domain>["<object_id>"]` for a
   digit-leading object_id), backed by `from hassle.registry import entities
   as e`. Lists become `[e.a.b, e.c.d]`. Jinja template strings and non-entity
   strings are untouched.
3. `from hassle import *` replaces the enumerated builder import. The
   `entities as e` import stays explicit.
4. Section comments (`# --- conditions ---` / `# --- actions ---`) precede
   each non-empty section in an automation body; `# --- sequence ---`
   precedes a script's sequence when non-empty. Triggers no longer have a
   body section comment at all -- they're emitted as the `triggers=` decorator
   kwarg now (``ux/triggers-in-decorator``, see test_decompile_triggers_in_
   decorator.py), which precedes the body entirely.
"""

from __future__ import annotations

from hassle.compiler.bundle import compile_bundle
from hassle.decompiler import decompile_bundle
from hassle.ir import parse, sha256_hash

# ---------------------------------------------------------------------------
# 1. alias-derived function names + collision handling
# ---------------------------------------------------------------------------


def test_automation_name_derived_from_alias_not_id() -> None:
    config = {
        "id": "1769413455954",
        "alias": "Hallway: light on motion",
        "triggers": [],
        "conditions": [],
        "actions": [],
    }
    obj = parse(config, kind="automation")
    source = decompile_bundle({obj.object_key(): obj})

    assert "def hallway_light_on_motion():" in source
    # I2: the id kwarg must still be present verbatim, untouched.
    assert 'id="1769413455954"' in source
    assert "def _1769413455954" not in source


def test_automation_without_alias_falls_back_to_automation_id() -> None:
    config = {"id": "42", "triggers": [], "conditions": [], "actions": []}
    obj = parse(config, kind="automation")
    source = decompile_bundle({obj.object_key(): obj})

    assert "def automation_42():" in source


def test_automation_alias_collision_gets_deterministic_suffix() -> None:
    config_a = {
        "id": "111",
        "alias": "Hallway Light",
        "triggers": [],
        "conditions": [],
        "actions": [],
    }
    config_b = {
        "id": "222",
        "alias": "Hallway Light",
        "triggers": [],
        "conditions": [],
        "actions": [],
    }
    obj_a = parse(config_a, kind="automation")
    obj_b = parse(config_b, kind="automation")
    objects = {obj_a.object_key(): obj_a, obj_b.object_key(): obj_b}
    source = decompile_bundle(objects)

    assert "def hallway_light():" in source
    assert "def hallway_light_2():" in source


def test_automation_alias_collision_suffix_is_deterministic_regardless_of_dict_order() -> None:
    config_a = {
        "id": "111",
        "alias": "Hallway Light",
        "triggers": [],
        "conditions": [],
        "actions": [],
    }
    config_b = {
        "id": "222",
        "alias": "Hallway Light",
        "triggers": [],
        "conditions": [],
        "actions": [],
    }
    obj_a = parse(config_a, kind="automation")
    obj_b = parse(config_b, kind="automation")
    forward = decompile_bundle({obj_a.object_key(): obj_a, obj_b.object_key(): obj_b})
    backward = decompile_bundle({obj_b.object_key(): obj_b, obj_a.object_key(): obj_a})

    assert forward == backward


def test_script_name_derived_from_alias_not_object_id() -> None:
    config = {"alias": "Movie Time", "sequence": []}
    obj = parse(config, kind="script", key_hint="9988")
    source = decompile_bundle({obj.object_key(): obj})

    assert "def movie_time():" in source
    assert 'id="9988"' in source


def test_script_without_alias_falls_back_to_script_id() -> None:
    config = {"sequence": []}
    obj = parse(config, kind="script", key_hint="movie_time")
    source = decompile_bundle({obj.object_key(): obj})

    assert "def script_movie_time():" in source


def test_helper_variable_name_still_derived_from_id() -> None:
    # Helpers are unaffected: id-derived variable name is right there already.
    config = {"id": "guest_mode", "name": "Guest Mode"}
    obj = parse(config, kind="input_boolean")
    source = decompile_bundle({obj.object_key(): obj})

    assert "guest_mode = input_boolean(" in source


# ---------------------------------------------------------------------------
# 2. entity references through the registry accessor
# ---------------------------------------------------------------------------


def test_state_trigger_entity_id_uses_registry_accessor() -> None:
    config = {
        "id": "1",
        "alias": "Motion Light",
        "triggers": [{"trigger": "state", "entity_id": "binary_sensor.hall_motion", "to": "on"}],
        "conditions": [],
        "actions": [],
    }
    obj = parse(config, kind="automation")
    source = decompile_bundle({obj.object_key(): obj})

    assert "state(e.binary_sensor.hall_motion)" in source
    assert '"binary_sensor.hall_motion"' not in source
    assert "from hassle.registry import entities as e" in source


def test_numeric_state_entity_id_uses_registry_accessor() -> None:
    config = {
        "id": "1",
        "alias": "Temp Check",
        "triggers": [{"trigger": "numeric_state", "entity_id": "sensor.temperature", "above": 20}],
        "conditions": [],
        "actions": [],
    }
    obj = parse(config, kind="automation")
    source = decompile_bundle({obj.object_key(): obj})

    assert "numeric_state(e.sensor.temperature, above=20)" in source


def test_target_entity_id_uses_registry_accessor_inside_dict() -> None:
    config = {
        "id": "1",
        "alias": "Turn On Hallway",
        "triggers": [],
        "conditions": [],
        "actions": [
            {"action": "light.turn_on", "target": {"entity_id": "light.hallway"}},
        ],
    }
    obj = parse(config, kind="automation")
    source = decompile_bundle({obj.object_key(): obj})

    assert 'target={"entity_id": e.light.hallway}' in source
    assert '"light.hallway"' not in source


def test_target_entity_id_list_becomes_list_of_registry_refs() -> None:
    config = {
        "id": "1",
        "alias": "Turn On Two",
        "triggers": [],
        "conditions": [],
        "actions": [
            {
                "action": "light.turn_on",
                "target": {"entity_id": ["light.hallway", "light.porch"]},
            },
        ],
    }
    obj = parse(config, kind="automation")
    source = decompile_bundle({obj.object_key(): obj})

    assert "[e.light.hallway, e.light.porch]" in source


def test_wait_for_trigger_entity_id_uses_registry_accessor() -> None:
    config = {
        "id": "1",
        "alias": "Wait For Door",
        "triggers": [],
        "conditions": [],
        "actions": [
            {
                "wait_for_trigger": [
                    {"trigger": "state", "entity_id": "binary_sensor.door", "to": "off"}
                ],
            },
        ],
    }
    obj = parse(config, kind="automation")
    source = decompile_bundle({obj.object_key(): obj})

    assert "state(e.binary_sensor.door)" in source


def test_digit_leading_object_id_uses_index_form() -> None:
    config = {
        "id": "1",
        "alias": "3D Printer Done",
        "triggers": [{"trigger": "state", "entity_id": "sensor.3d_printer", "to": "idle"}],
        "conditions": [],
        "actions": [],
    }
    obj = parse(config, kind="automation")
    source = decompile_bundle({obj.object_key(): obj})

    assert 'state(e.sensor["3d_printer"])' in source


def test_state_value_is_not_turned_into_an_entity_ref() -> None:
    # `.to()`/`.is_()` values are state *values*, never entity positions, even
    # when they happen to look domain.object_id-shaped.
    config = {
        "id": "1",
        "alias": "Weird State Value",
        "triggers": [
            {"trigger": "state", "entity_id": "binary_sensor.hall_motion", "to": "device.mode"}
        ],
        "conditions": [],
        "actions": [],
    }
    obj = parse(config, kind="automation")
    source = decompile_bundle({obj.object_key(): obj})

    assert '.to("device.mode")' in source


def test_jinja_template_string_is_not_turned_into_an_entity_ref() -> None:
    config = {
        "id": "1",
        "alias": "Template Condition",
        "triggers": [],
        "conditions": [
            {
                "condition": "template",
                "value_template": "{{ states('light.hallway') == 'on' }}",
            }
        ],
        "actions": [],
    }
    obj = parse(config, kind="automation")
    source = decompile_bundle({obj.object_key(): obj})

    assert "{{ states('light.hallway') == 'on' }}" in source
    assert "e.light.hallway" not in source


def test_helper_declaration_ref_used_as_entity_uses_registry_accessor() -> None:
    config = {
        "id": "1",
        "alias": "Guest Mode Light",
        "triggers": [{"trigger": "state", "entity_id": "input_boolean.guest_mode", "to": "on"}],
        "conditions": [],
        "actions": [],
    }
    obj = parse(config, kind="automation")
    source = decompile_bundle({obj.object_key(): obj})

    assert "state(e.input_boolean.guest_mode)" in source


def test_entity_ref_compiles_byte_identical_ir() -> None:
    """EntityRef is a str subclass: recompiling the e.-ref form must produce
    IR that hashes identically to the original (zero drift, I3)."""
    config = {
        "id": "1",
        "alias": "Hallway Light On Motion",
        "triggers": [{"trigger": "state", "entity_id": "binary_sensor.hall_motion", "to": "on"}],
        "conditions": [],
        "actions": [
            {"action": "light.turn_on", "target": {"entity_id": "light.hallway"}},
        ],
    }
    obj = parse(config, kind="automation")
    source = decompile_bundle({obj.object_key(): obj})

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "objects.py").write_text(source, encoding="utf-8")
        result = compile_bundle(tmp)

    assert len(result.objects) == 1
    (recompiled,) = result.objects.values()
    assert sha256_hash(recompiled.to_ha()) == sha256_hash(obj.to_ha())


# ---------------------------------------------------------------------------
# 3. star import
# ---------------------------------------------------------------------------


def test_bundle_emits_star_import_and_explicit_entities_import() -> None:
    config = {"id": "1", "alias": "Anything", "triggers": [], "conditions": [], "actions": []}
    obj = parse(config, kind="automation")
    source = decompile_bundle({obj.object_key(): obj})

    assert "from hassle import *" in source
    assert "from hassle.registry import entities as e" in source
    # No more enumerated builder-name import.
    assert "from hassle import automation," not in source


# ---------------------------------------------------------------------------
# 4. section comments
# ---------------------------------------------------------------------------


def test_automation_body_gets_section_comments_for_nonempty_sections() -> None:
    config = {
        "id": "1",
        "alias": "Full Sections",
        "triggers": [{"trigger": "state", "entity_id": "binary_sensor.hall_motion", "to": "on"}],
        "conditions": [{"condition": "state", "entity_id": "sun.sun", "state": "below_horizon"}],
        "actions": [
            {"action": "light.turn_on", "target": {"entity_id": "light.hallway"}},
        ],
    }
    obj = parse(config, kind="automation")
    source = decompile_bundle({obj.object_key(): obj})

    # Triggers no longer get a body section comment at all -- they're in the
    # `triggers=` decorator kwarg (ux/triggers-in-decorator).
    assert "# --- triggers ---" not in source
    assert "# --- conditions ---" in source
    assert "# --- actions ---" in source
    # Ordering: conditions, then actions.
    cond_idx = source.index("# --- conditions ---")
    act_idx = source.index("# --- actions ---")
    assert cond_idx < act_idx


def test_automation_body_omits_section_comment_for_empty_sections() -> None:
    config = {
        "id": "1",
        "alias": "Only Actions",
        "triggers": [],
        "conditions": [],
        "actions": [
            {"action": "light.turn_on", "target": {"entity_id": "light.hallway"}},
        ],
    }
    obj = parse(config, kind="automation")
    source = decompile_bundle({obj.object_key(): obj})

    assert "# --- triggers ---" not in source
    assert "# --- conditions ---" not in source
    assert "# --- actions ---" in source


def test_script_sequence_gets_section_comment_when_nonempty() -> None:
    config = {
        "alias": "Movie Time",
        "sequence": [
            {"action": "light.turn_off", "target": {"entity_id": "light.hallway"}},
        ],
    }
    obj = parse(config, kind="script", key_hint="movie_time")
    source = decompile_bundle({obj.object_key(): obj})

    assert "# --- sequence ---" in source


def test_script_sequence_omits_section_comment_when_empty() -> None:
    config = {"alias": "Nothing To Do", "sequence": []}
    obj = parse(config, kind="script", key_hint="noop")
    source = decompile_bundle({obj.object_key(): obj})

    assert "# --- sequence ---" not in source


# ---------------------------------------------------------------------------
# stability under the new style (R8)
# ---------------------------------------------------------------------------


def test_decompile_with_new_style_is_still_byte_stable() -> None:
    config = {
        "id": "1769413455954",
        "alias": "Hallway: light on motion",
        "triggers": [{"trigger": "state", "entity_id": "binary_sensor.hall_motion", "to": "on"}],
        "conditions": [],
        "actions": [
            {"action": "light.turn_on", "target": {"entity_id": "light.hallway"}},
        ],
    }
    obj = parse(config, kind="automation")
    objects = {obj.object_key(): obj}
    first = decompile_bundle(objects)
    second = decompile_bundle(objects)
    assert first == second
