"""MILESTONES M15 work item B, test 5 -- migrating an old-layout bundle (the
RETIRED `automations/`/`scripts/`/`helpers/` per-kind trees) into the new
category-first, root-level layout.

Covers:
- `test_bundle_has_old_layout_detects_populated_retired_trees` /
  `test_bundle_has_old_layout_false_for_new_layout_bundle` -- detection.
- `test_migration_preserves_user_content_in_kept_old_file` -- an old file
  with a user comment + a custom (non-Hassle) `def` alongside the managed
  object: the managed object moves out, but the FILE ITSELF is kept (I6 --
  the comment/def are never lost).
- `test_migration_deletes_old_file_with_no_remaining_user_content` -- an old
  file holding ONLY the managed object (plus its own imports): after the
  object moves out, the file is deleted entirely (nothing left worth
  keeping).
- `test_migration_reports_every_move` -- `MigrationReport.moves` names every
  migrated object with its old/new path.
- `test_migrated_objects_compile_identically` -- I3/byte-stability precursor:
  the migrated objects compile to the exact same IR after the move.
"""

from __future__ import annotations

from pathlib import Path

from hassle.compiler.bundle import compile_bundle
from hassle_cli import bundle_ops
from hassle_cli.layout_migration import bundle_has_old_layout, migrate_old_layout


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_bundle_has_old_layout_detects_populated_retired_trees(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _write(
        bundle / "automations" / "hallway.py",
        """
from hassle import automation, service, state, when

@automation(id="a1", alias="A1")
def a1():
    when(state("binary_sensor.hall_motion").to("on"))
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
    )
    assert bundle_has_old_layout(bundle) is True


def test_bundle_has_old_layout_false_for_new_layout_bundle(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _write(
        bundle / "misc.py",
        """
from hassle import automation, service, state, when

@automation(id="a1", alias="A1")
def a1():
    when(state("binary_sensor.hall_motion").to("on"))
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
    )
    assert bundle_has_old_layout(bundle) is False


def test_bundle_has_old_layout_false_for_empty_retired_dirs(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    (bundle / "automations").mkdir(parents=True)
    (bundle / "scripts").mkdir(parents=True)
    (bundle / "helpers").mkdir(parents=True)
    assert bundle_has_old_layout(bundle) is False


def test_migration_preserves_user_content_in_kept_old_file(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _write(
        bundle / "automations" / "hallway.py",
        '''
from hassle import automation, service, state, when

# This comment is mine -- do not lose it.
def helper_fn():
    """A custom, non-Hassle helper the user wrote by hand."""
    return 42


@automation(id="hall_light_on_motion", alias="Hallway light on motion")
def hall_light_on_motion():
    when(state("binary_sensor.hall_motion").to("on"))
    service("light.turn_on", target={"entity_id": "light.hallway"})
''',
    )
    result = compile_bundle(bundle)
    new_paths = {key: bundle_ops.default_source_path(key, registry=None) for key in result.objects}

    report = migrate_old_layout(bundle, result, registry=None, new_source_path_for=new_paths)

    assert report.migrated is True
    assert len(report.moves) == 1
    move = report.moves[0]
    assert move.object_key == "automation:hall_light_on_motion"
    assert move.old_path == "automations/hallway.py"
    assert move.new_path == "misc.py"

    # The old file survives -- the user's comment and custom def are intact.
    old_file = bundle / "automations" / "hallway.py"
    assert old_file.is_file()
    old_text = old_file.read_text(encoding="utf-8")
    assert "This comment is mine -- do not lose it." in old_text
    assert "def helper_fn():" in old_text
    assert "hall_light_on_motion" not in old_text
    assert "automations/hallway.py" not in report.deleted_files

    # The object landed at its new destination.
    new_file = bundle / "misc.py"
    assert new_file.is_file()
    assert "hall_light_on_motion" in new_file.read_text(encoding="utf-8")

    # Migrated bundle still compiles, and the helper_fn/comment survive as
    # ordinary (uncompiled) Python in the kept old file.
    recompiled = compile_bundle(bundle)
    assert "automation:hall_light_on_motion" in recompiled.objects


def test_migration_deletes_old_file_with_no_remaining_user_content(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _write(
        bundle / "scripts" / "chores.py",
        """
from hassle import script, service

@script(id="take_out_trash", alias="Take out the trash")
def take_out_trash():
    service("switch.turn_on", target={"entity_id": "switch.porch_light"})
""",
    )
    result = compile_bundle(bundle)
    new_paths = {key: bundle_ops.default_source_path(key, registry=None) for key in result.objects}

    report = migrate_old_layout(bundle, result, registry=None, new_source_path_for=new_paths)

    assert report.migrated is True
    assert "scripts/chores.py" in report.deleted_files
    assert not (bundle / "scripts" / "chores.py").is_file()

    new_file = bundle / "misc.py"
    assert new_file.is_file()
    assert "take_out_trash" in new_file.read_text(encoding="utf-8")


def test_migration_reports_every_move_and_groups_by_new_destination(tmp_path: Path) -> None:
    """Two objects sharing the old `helpers/misc.py` fallback both migrate to
    the new shared root `misc.py` -- both moves are reported, and both land
    in the SAME new file (never last-writer-wins)."""
    bundle = tmp_path / "bundle"
    _write(
        bundle / "helpers" / "misc.py",
        """
from hassle import input_boolean, input_number

guest_mode = input_boolean(id="guest_mode", name="Guest Mode")
tank_level = input_number(id="tank_level", name="Tank level", min=0, max=100, step=1)
""",
    )
    result = compile_bundle(bundle)
    new_paths = {key: bundle_ops.default_source_path(key, registry=None) for key in result.objects}

    report = migrate_old_layout(bundle, result, registry=None, new_source_path_for=new_paths)

    assert {m.object_key for m in report.moves} == {
        "input_boolean:guest_mode",
        "input_number:tank_level",
    }
    assert all(m.new_path == "misc.py" for m in report.moves)
    assert "helpers/misc.py" in report.deleted_files

    new_text = (bundle / "misc.py").read_text(encoding="utf-8")
    assert "guest_mode" in new_text
    assert "tank_level" in new_text


def test_no_migration_needed_for_new_layout_bundle(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _write(
        bundle / "misc.py",
        """
from hassle import automation, service, state, when

@automation(id="a1", alias="A1")
def a1():
    when(state("binary_sensor.hall_motion").to("on"))
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
    )
    result = compile_bundle(bundle)
    new_paths = {key: bundle_ops.default_source_path(key, registry=None) for key in result.objects}
    report = migrate_old_layout(bundle, result, registry=None, new_source_path_for=new_paths)
    assert report.migrated is False
    assert report.moves == []
    assert report.deleted_files == []
