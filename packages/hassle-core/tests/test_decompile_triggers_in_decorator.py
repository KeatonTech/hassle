"""Decompiler emits `triggers=` in the decorator as the canonical form (owner-
approved DSL evolution, task #10; DESIGN §5.3/§5.5/§7.3, docs/dsl-extensions.md).

The decompiler no longer emits `when(...)` in the automation body: triggers
become a `triggers=[...]` kwarg on `@automation(...)` (multi-line formatted
when there is more than one trigger, matching the pre-existing `when(...)`
multi-trigger formatting convention). `when()` itself is untouched and remains
importable/usable (F3: additions never remove).

Section comments (`# --- conditions ---`/`# --- actions ---`) were removed
entirely in a later round (`ux/dsl-ergonomics`, owner amendment -- see
`test_no_section_comments_ever_emitted` below and DESIGN §7.3's dated note):
once conditions also moved to the `with only_if(...):` block form, the body's
structure became self-describing on its own.
"""

from __future__ import annotations

from hassle.compiler.bundle import compile_bundle
from hassle.decompiler import decompile_bundle
from hassle.ir import parse, sha256_hash


def test_single_trigger_emitted_as_decorator_kwarg() -> None:
    config = {
        "id": "1",
        "alias": "Motion Light",
        "triggers": [{"trigger": "state", "entity_id": "binary_sensor.hall_motion", "to": "on"}],
        "conditions": [],
        "actions": [],
    }
    obj = parse(config, kind="automation")
    source = decompile_bundle({obj.object_key(): obj})

    assert "triggers=[state(e.binary_sensor.hall_motion).to(" in source
    # No more when() in the body, and no triggers section comment.
    assert "when(" not in source
    assert "# --- triggers ---" not in source


def test_multiple_triggers_emitted_multiline_in_decorator() -> None:
    config = {
        "id": "1",
        "alias": "Multi Trigger",
        "triggers": [
            {"trigger": "state", "entity_id": "binary_sensor.hall_motion", "to": "on"},
            {"trigger": "state", "entity_id": "binary_sensor.door", "to": "off"},
        ],
        "conditions": [],
        "actions": [],
    }
    obj = parse(config, kind="automation")
    source = decompile_bundle({obj.object_key(): obj})

    assert "triggers=[" in source
    assert "when(" not in source
    # Multi-line formatting: each trigger on its own line inside the list.
    assert "state(e.binary_sensor.hall_motion).to(" in source
    assert "state(e.binary_sensor.door).to(" in source


def test_raw_trigger_still_emitted_as_body_statement() -> None:
    # A raw (untyped) trigger can't be nested inside a decorator kwarg list
    # expression the same way a typed builder call can -- typed triggers still
    # go in `triggers=`, but an untyped one stays a `raw_trigger(...)` body
    # statement (it's a *verb*, not an expression: it calls record_trigger
    # itself and returns None).
    config = {
        "id": "1",
        "alias": "Raw Trigger",
        "triggers": [{"trigger": "totally_unmodeled_type", "foo": "bar"}],
        "conditions": [],
        "actions": [],
    }
    obj = parse(config, kind="automation")
    source = decompile_bundle({obj.object_key(): obj})

    assert "raw_trigger(" in source


def test_no_section_comments_ever_emitted() -> None:
    # Updated (`ux/dsl-ergonomics`, owner amendment -- supersedes this test's
    # original expectation): section comments are removed entirely, not just
    # the triggers one. With conditions now emitted as the `with only_if(...):`
    # block form (item 1) wrapping every action, the body's structure --
    # decorator = when, only_if block = gate, plain statements = do -- no
    # longer needs a comment to be legible. See DESIGN §7.3's dated note.
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

    assert "# --- triggers ---" not in source
    assert "# --- conditions ---" not in source
    assert "# --- actions ---" not in source
    # Conditions now wrap the actions in a `with only_if(...):` block.
    assert "with only_if(" in source


def test_no_triggers_at_all_emits_no_triggers_kwarg() -> None:
    config = {"id": "1", "alias": "No Triggers", "triggers": [], "conditions": [], "actions": []}
    obj = parse(config, kind="automation")
    source = decompile_bundle({obj.object_key(): obj})

    assert "triggers=" not in source


def test_decorator_triggers_recompile_byte_identical_ir() -> None:
    """Compile parity via the decompiler path too: decompiling a config with
    triggers, then recompiling the decorator-form output, must reproduce
    byte-identical IR (I3)."""
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


def test_decompile_with_decorator_triggers_is_still_byte_stable() -> None:
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
