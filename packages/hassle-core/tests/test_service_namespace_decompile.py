"""M18 milestone test 3 — decompiler canonical form for typed service
namespaces.

Canonical form: a plain service-call action whose literal `"domain.service"`
exists in the registry snapshot AND whose data is kwarg-expressible (every key
a valid Python identifier, not a reserved word) emits the namespace call
(`light.turn_on(target=..., **fields)`) plus a per-file
`from hassle.services import <domains>` import line. Everything else
(templated service name, snapshot-absent service, no snapshot at all,
non-kwarg-safe data keys) falls back to today's `service(...)` (I3 byte-exact
through BOTH branches).
"""

from __future__ import annotations

from pathlib import Path

from hassle.compiler.bundle import compile_bundle
from hassle.decompiler import decompile_bundle
from hassle.ir import parse
from hassle.registry.snapshot import RegistrySnapshot

REPO_ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT = RegistrySnapshot.load(REPO_ROOT / "fixtures" / "registry" / "home.json")


def _light_turn_on_action() -> dict[str, object]:
    return {
        "action": "light.turn_on",
        "target": {"entity_id": "light.hallway"},
        "data": {"brightness_pct": 60},
    }


def _automation(actions: list[dict[str, object]]) -> dict[str, object]:
    return {
        "id": "x",
        "alias": "x",
        "triggers": [],
        "conditions": [],
        "actions": actions,
    }


def test_snapshot_present_plain_call_emits_namespace_form() -> None:
    obj = parse(_automation([_light_turn_on_action()]), kind="automation", key_hint="x")
    source = decompile_bundle({obj.object_key(): obj}, snapshot=SNAPSHOT)
    assert "light.turn_on(target=" in source
    assert "from hassle.services import light" in source
    assert "service(" not in source


def test_no_snapshot_falls_back_to_service_call() -> None:
    obj = parse(_automation([_light_turn_on_action()]), kind="automation", key_hint="x")
    source = decompile_bundle({obj.object_key(): obj})
    assert "service(" in source
    assert "from hassle.services import" not in source


def test_snapshot_absent_service_falls_back_to_service_call() -> None:
    action = {
        "action": "light.definitely_not_a_real_service",
        "target": {"entity_id": "light.hallway"},
    }
    obj = parse(_automation([action]), kind="automation", key_hint="x")
    source = decompile_bundle({obj.object_key(): obj}, snapshot=SNAPSHOT)
    assert "service(" in source
    assert "from hassle.services import" not in source


def test_templated_service_name_falls_back_to_service_call() -> None:
    action = {
        "action": "{{ 'light.turn_on' }}",
        "target": {"entity_id": "light.hallway"},
    }
    obj = parse(_automation([action]), kind="automation", key_hint="x")
    source = decompile_bundle({obj.object_key(): obj}, snapshot=SNAPSHOT)
    assert "service(" in source


def test_non_identifier_data_key_falls_back_to_service_call() -> None:
    # A data key that isn't a valid Python identifier (e.g. contains a dash,
    # or is a reserved keyword) can't be expressed as a kwarg.
    action = {
        "action": "light.turn_on",
        "target": {"entity_id": "light.hallway"},
        "data": {"class": "foo"},  # `class` is a reserved word
    }
    obj = parse(_automation([action]), kind="automation", key_hint="x")
    source = decompile_bundle({obj.object_key(): obj}, snapshot=SNAPSHOT)
    assert "service(" in source
    assert "from hassle.services import" not in source


def test_reserved_word_data_key_falls_back() -> None:
    action = {
        "action": "light.turn_on",
        "target": {"entity_id": "light.hallway"},
        "data": {"import": "foo"},
    }
    obj = parse(_automation([action]), kind="automation", key_hint="x")
    source = decompile_bundle({obj.object_key(): obj}, snapshot=SNAPSHOT)
    assert "service(" in source


def test_namespace_form_round_trips_byte_stable(tmp_path: Path) -> None:
    obj = parse(_automation([_light_turn_on_action()]), kind="automation", key_hint="x")
    source = decompile_bundle({obj.object_key(): obj}, snapshot=SNAPSHOT)
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "objects.py").write_text(source, encoding="utf-8")
    result = compile_bundle(bundle_dir)
    (recompiled,) = result.objects.values()
    assert recompiled.to_ha() == _automation([_light_turn_on_action()])


def test_service_fallback_form_round_trips_byte_stable(tmp_path: Path) -> None:
    action = {
        "action": "light.definitely_not_a_real_service",
        "target": {"entity_id": "light.hallway"},
    }
    obj = parse(_automation([action]), kind="automation", key_hint="x")
    source = decompile_bundle({obj.object_key(): obj}, snapshot=SNAPSHOT)
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "objects.py").write_text(source, encoding="utf-8")
    result = compile_bundle(bundle_dir)
    (recompiled,) = result.objects.values()
    assert recompiled.to_ha() == _automation([action])


def test_import_lines_sorted_deterministically_multi_domain() -> None:
    actions = [
        {"action": "switch.turn_on", "target": {"entity_id": "switch.porch"}},
        {"action": "light.turn_on", "target": {"entity_id": "light.hallway"}},
    ]
    obj = parse(_automation(actions), kind="automation", key_hint="x")
    source = decompile_bundle({obj.object_key(): obj}, snapshot=SNAPSHOT)
    assert "from hassle.services import light, switch" in source


def test_domain_colliding_with_star_import_surface_gets_aliased(tmp_path: Path) -> None:
    """Regression (found via the fixture corpus's own `automation.trigger`-
    calling fixtures): `automation` is BOTH a real HA service domain and the
    frozen `@automation` decorator name. A plain, unaliased
    `from hassle.services import automation` would silently shadow the
    decorator import (later import wins at module scope), breaking every
    automation in the file. The namespace form must alias the import
    (`from hassle.services import automation as svc_automation`) and call
    through the alias, and this must round-trip byte-stably."""
    action = {"action": "automation.trigger", "target": {"entity_id": "automation.other"}}
    obj = parse(_automation([action]), kind="automation", key_hint="x")
    source = decompile_bundle({obj.object_key(): obj}, snapshot=SNAPSHOT)
    assert "from hassle.services import automation as svc_automation" in source
    assert "svc_automation.trigger(" in source
    # The decorator's own `automation` name must be untouched/unshadowed.
    assert "@automation(" in source

    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "objects.py").write_text(source, encoding="utf-8")
    result = compile_bundle(bundle_dir)
    (recompiled,) = result.objects.values()
    assert recompiled.to_ha() == _automation([action])


def test_refresh_splice_merges_namespace_import(tmp_path: Path) -> None:
    """The single-object splice-refresh path (`SplicingSourceWriter.
    splice_object`) must merge a new `from hassle.services import <domain>`
    line into an existing file via the existing `merge_missing_imports` seam,
    the same way it already merges other missing imports."""
    from hassle.sync.source_writer import SplicingSourceWriter

    existing_source = (
        "from hassle import automation, service\n"
        "from hassle.registry import entities as e\n"
        "\n\n"
        "@automation(id='other', alias='other')\n"
        "def other():\n"
        "    service('script.turn_on', target={'entity_id': 'script.x'})\n"
    )
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    target_file = bundle_dir / "objects.py"
    target_file.write_text(existing_source, encoding="utf-8")

    obj = parse(_automation([_light_turn_on_action()]), kind="automation", key_hint="x")
    new_source = decompile_bundle({obj.object_key(): obj}, snapshot=SNAPSHOT)

    writer = SplicingSourceWriter(updated_on="2026-07-06")
    writer.splice_object(target_file, obj.object_key(), new_source)

    written = target_file.read_text(encoding="utf-8")
    assert "from hassle.services import light" in written
    # The recompiled file must still compile (both objects present).
    result = compile_bundle(bundle_dir)
    assert len(result.objects) == 2
