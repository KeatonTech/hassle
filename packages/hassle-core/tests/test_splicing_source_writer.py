"""`SplicingSourceWriter` — the LibCST splicer wired into the SourceWriter/plan seam.

Regression companion to `hassle-cli/tests/test_pull_refresh_splice.py` (pull's
REFRESH clobbered sibling objects sharing a source file, because the CLI used
`WholeFileSourceWriter`'s documented whole-file stand-in): a real
`SourceWriter` whose `splice_object` surgically replaces one object's
statement (and whose `delete_object` surgically removes one), leaving every
sibling statement and hand-written comment untouched (no local or UI edit is
ever silently lost).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hassle.sync.source_writer import (
    SourceWriteOutsideBundleRootError,
    SourceWriter,
    SplicingSourceWriter,
    SymlinkWriteRefusedError,
)

TWO_AUTOMATIONS = """\
from hassle import automation, service, state, when


@automation(id="hall_light_on_motion", alias="Hallway light on motion")
def hall_light_on_motion():
    when(state("binary_sensor.hall_motion").to("on"))
    service("light.turn_on", target={"entity_id": "light.hallway"})


# Hand-written note about the porch automation.
@automation(id="porch_light_on_motion", alias="Porch light on motion")
def porch_light_on_motion():
    when(state("binary_sensor.porch_motion").to("on"))
    service("light.turn_on", target={"entity_id": "light.porch"})
"""

PORCH_BLOCK = (
    "# Hand-written note about the porch automation.\n"
    '@automation(id="porch_light_on_motion", alias="Porch light on motion")\n'
    "def porch_light_on_motion():\n"
    '    when(state("binary_sensor.porch_motion").to("on"))\n'
    '    service("light.turn_on", target={"entity_id": "light.porch"})\n'
)

# Shaped like real `decompile_bundle` single-object output: the decompiler's
# import header plus ONE object statement, whose (alias-derived) function name
# differs from the def name currently in the file.
HALL_REPLACEMENT = """\
from hassle import *
from hassle.registry import entities as e


@automation(id="hall_light_on_motion", alias="Hallway light on motion (UI edit)")
def hallway_light_on_motion_ui_edit():
    when(state("binary_sensor.hall_motion").to("on"))
    service("light.turn_on", target={"entity_id": "light.hallway"})
"""


def _write(tmp_path: Path, content: str = TWO_AUTOMATIONS) -> Path:
    target = tmp_path / "hallway.py"
    target.write_text(content, encoding="utf-8")
    return target


def test_splice_replaces_only_the_target_object(tmp_path: Path) -> None:
    writer = SplicingSourceWriter(updated_on="2026-07-04")
    target = _write(tmp_path)

    writer.splice_object(target, "automation:hall_light_on_motion", HALL_REPLACEMENT)

    after = target.read_text(encoding="utf-8")
    assert PORCH_BLOCK in after, after
    assert "Hallway light on motion (UI edit)" in after
    assert 'alias="Hallway light on motion")' not in after
    assert "# hassle: updated from UI on 2026-07-04" in after


def test_splice_matches_target_by_decorator_id_not_def_name(tmp_path: Path) -> None:
    # The def name in the file need not equal the object id -- identity is the
    # decorator's id= kwarg (falling back to the function name, like
    # `hassle.compiler.registry._register` does at compile time).
    source = TWO_AUTOMATIONS.replace("def hall_light_on_motion():", "def hall_motion():")
    writer = SplicingSourceWriter(updated_on="2026-07-04")
    target = _write(tmp_path, source)

    writer.splice_object(target, "automation:hall_light_on_motion", HALL_REPLACEMENT)

    after = target.read_text(encoding="utf-8")
    assert "def hall_motion():" not in after
    assert "Hallway light on motion (UI edit)" in after
    assert PORCH_BLOCK in after, after


def test_splice_matches_target_by_def_name_when_no_id_kwarg(tmp_path: Path) -> None:
    source = TWO_AUTOMATIONS.replace(
        '@automation(id="hall_light_on_motion", alias="Hallway light on motion")',
        '@automation(alias="Hallway light on motion")',
    )
    writer = SplicingSourceWriter(updated_on="2026-07-04")
    target = _write(tmp_path, source)

    writer.splice_object(target, "automation:hall_light_on_motion", HALL_REPLACEMENT)

    after = target.read_text(encoding="utf-8")
    assert "Hallway light on motion (UI edit)" in after
    assert PORCH_BLOCK in after, after


def test_splice_merges_missing_imports_exactly_once(tmp_path: Path) -> None:
    writer = SplicingSourceWriter(updated_on="2026-07-04")
    target = _write(tmp_path)

    writer.splice_object(target, "automation:hall_light_on_motion", HALL_REPLACEMENT)
    once = target.read_text(encoding="utf-8")
    assert once.count("from hassle.registry import entities as e") == 1
    # The file's own hand-picked import line is untouched.
    assert "from hassle import automation, service, state, when" in once

    # Idempotent: a second refresh never duplicates the merged imports.
    writer.splice_object(target, "automation:hall_light_on_motion", HALL_REPLACEMENT)
    twice = target.read_text(encoding="utf-8")
    assert twice.count("from hassle.registry import entities as e") == 1
    assert twice.count("from hassle import *") == 1


def test_splice_missing_file_writes_whole_content(tmp_path: Path) -> None:
    writer = SplicingSourceWriter(updated_on="2026-07-04")
    target = tmp_path / "not_yet" / "hallway.py"

    writer.splice_object(target, "automation:hall_light_on_motion", HALL_REPLACEMENT)

    assert target.read_text(encoding="utf-8") == HALL_REPLACEMENT


def test_splice_object_absent_from_file_appends_never_clobbers(tmp_path: Path) -> None:
    # A stale manifest can point a refresh at a file the object is no longer
    # in -- the siblings must survive (no edit is silently lost); the
    # refreshed def is appended.
    writer = SplicingSourceWriter(updated_on="2026-07-04")
    target = _write(tmp_path)

    writer.splice_object(target, "automation:closet_light_on_motion", HALL_REPLACEMENT)

    after = target.read_text(encoding="utf-8")
    assert PORCH_BLOCK in after, after
    assert "def hall_light_on_motion():" in after
    assert "def hallway_light_on_motion_ui_edit():" in after
    assert "# hassle: updated from UI on 2026-07-04" in after


def test_unspliceable_replacement_falls_back_to_whole_file_write(tmp_path: Path) -> None:
    # Deliberately broken decompiler output (not parseable as one statement):
    # keep the old whole-file behavior so the CLI's post-write compile
    # backstop still catches it and the file is left in place for diagnosis.
    writer = SplicingSourceWriter(updated_on="2026-07-04")
    target = _write(tmp_path)
    broken = "def broken(:\n    pass\n"

    writer.splice_object(target, "automation:hall_light_on_motion", broken)

    assert target.read_text(encoding="utf-8") == broken


def test_delete_object_removes_only_the_target(tmp_path: Path) -> None:
    writer = SplicingSourceWriter(updated_on="2026-07-04")
    target = _write(tmp_path)

    writer.delete_object(target, "automation:hall_light_on_motion")

    after = target.read_text(encoding="utf-8")
    assert "def hall_light_on_motion():" not in after
    assert PORCH_BLOCK in after, after


def test_delete_last_object_removes_the_file(tmp_path: Path) -> None:
    single = """\
from hassle import automation, service, state, when


@automation(id="hall_light_on_motion", alias="Hallway light on motion")
def hall_light_on_motion():
    when(state("binary_sensor.hall_motion").to("on"))
    service("light.turn_on", target={"entity_id": "light.hallway"})
"""
    writer = SplicingSourceWriter(updated_on="2026-07-04")
    target = _write(tmp_path, single)

    writer.delete_object(target, "automation:hall_light_on_motion")

    assert not target.exists()


def test_delete_object_absent_from_file_is_noop(tmp_path: Path) -> None:
    # The whole-file writer unlinked the file even when the object wasn't in
    # it -- surgically, an absent object means there is nothing to delete.
    writer = SplicingSourceWriter(updated_on="2026-07-04")
    target = _write(tmp_path)

    writer.delete_object(target, "automation:closet_light_on_motion")

    assert target.read_text(encoding="utf-8") == TWO_AUTOMATIONS


def test_delete_missing_file_is_noop(tmp_path: Path) -> None:
    writer = SplicingSourceWriter(updated_on="2026-07-04")
    writer.delete_object(tmp_path / "never_existed.py", "automation:gone")  # must not raise


def test_splicing_source_writer_satisfies_protocol(tmp_path: Path) -> None:
    assert isinstance(SplicingSourceWriter(updated_on="2026-07-04"), SourceWriter)


# ---------------------------------------------------------------------------
# Write-side containment (security hardening -- module docstring of
# `hassle.sync.source_writer`). `SplicingSourceWriter.splice_object`/
# `delete_object` read the destination (`path.exists()`/`read_text()`)
# BEFORE delegating to `write_whole_file` for the actual write, so they need
# their own up-front check -- covered separately from
# `test_source_writer.py`'s `WholeFileSourceWriter` coverage.
# ---------------------------------------------------------------------------


def test_splice_object_refuses_path_outside_bundle_root(tmp_path: Path) -> None:
    bundle_root = tmp_path / "bundle"
    bundle_root.mkdir()
    writer = SplicingSourceWriter(updated_on="2026-07-04", bundle_root=bundle_root)
    with pytest.raises(SourceWriteOutsideBundleRootError):
        writer.splice_object(Path("../escaped.py"), "automation:x", HALL_REPLACEMENT)
    assert not (tmp_path / "escaped.py").exists()


def test_splice_object_allows_normal_path_within_bundle_root(tmp_path: Path) -> None:
    bundle_root = tmp_path
    (bundle_root / "hallway.py").write_text(TWO_AUTOMATIONS, encoding="utf-8")
    writer = SplicingSourceWriter(updated_on="2026-07-04", bundle_root=bundle_root)

    writer.splice_object(Path("hallway.py"), "automation:hall_light_on_motion", HALL_REPLACEMENT)

    after = (bundle_root / "hallway.py").read_text(encoding="utf-8")
    assert "Hallway light on motion (UI edit)" in after
    assert PORCH_BLOCK in after, after


def test_delete_object_refuses_path_outside_bundle_root(tmp_path: Path) -> None:
    bundle_root = tmp_path / "bundle"
    bundle_root.mkdir()
    outside = tmp_path / "escaped.py"
    outside.write_text(TWO_AUTOMATIONS, encoding="utf-8")
    writer = SplicingSourceWriter(updated_on="2026-07-04", bundle_root=bundle_root)
    with pytest.raises(SourceWriteOutsideBundleRootError):
        writer.delete_object(outside, "automation:hall_light_on_motion")
    assert outside.read_text(encoding="utf-8") == TWO_AUTOMATIONS


def test_splice_object_refuses_dangling_symlink(tmp_path: Path) -> None:
    """The reported vulnerability: a dangling symlink committed in a bundle
    (`misc.py -> /outside/target`) has `exists() is False`, so the old code
    fell straight through `if not path.exists(): self.write_whole_file(...)`
    into a write outside the bundle. Now refused before that check runs."""
    target = tmp_path / "misc.py"
    target.symlink_to(tmp_path / "nonexistent" / "target.py")
    writer = SplicingSourceWriter(updated_on="2026-07-04")

    with pytest.raises(SymlinkWriteRefusedError):
        writer.splice_object(target, "automation:hall_light_on_motion", HALL_REPLACEMENT)
    assert not (tmp_path / "nonexistent").exists()


def test_splice_object_refuses_non_dangling_symlink_no_raw_traceback(tmp_path: Path) -> None:
    """A non-dangling symlink to a non-Python file must not reach
    `hassle.decompiler.splice`'s LibCST parser (which would surface as a raw
    traceback) -- refused with a clear `SymlinkWriteRefusedError` instead."""
    real_file = tmp_path / "notes.txt"
    real_file.write_text("just some prose, not python at all {{{ ]][[ \n", encoding="utf-8")
    link = tmp_path / "misc.py"
    link.symlink_to(real_file)
    writer = SplicingSourceWriter(updated_on="2026-07-04")

    with pytest.raises(SymlinkWriteRefusedError):
        writer.splice_object(link, "automation:hall_light_on_motion", HALL_REPLACEMENT)
    assert real_file.read_text(encoding="utf-8").startswith("just some prose")


def test_delete_object_refuses_symlink(tmp_path: Path) -> None:
    real_file = tmp_path / "hallway.py"
    real_file.write_text(TWO_AUTOMATIONS, encoding="utf-8")
    link = tmp_path / "misc.py"
    link.symlink_to(real_file)
    writer = SplicingSourceWriter(updated_on="2026-07-04")

    with pytest.raises(SymlinkWriteRefusedError):
        writer.delete_object(link, "automation:hall_light_on_motion")
    assert real_file.read_text(encoding="utf-8") == TWO_AUTOMATIONS


# ---------------------------------------------------------------------------
# Loop-splice reconcile warning. A compile-time loop
# generates an object with no single literal statement for the splicer to
# target -- the append path fires (same as a stale-manifest miss), but here
# the file's CURRENT content already compiles to that object key (it's
# metaprogrammed, not actually missing), so the append is about to create a
# same-file duplicate the next compile will reject.
# ---------------------------------------------------------------------------

LOOP_GENERATED_ROOMS = """\
from hassle import automation, service, state, when

ROOMS = ["kitchen", "office"]

for room in ROOMS:

    @automation(id=f"motion_{room}", alias=f"Motion light: {room}")
    def _motion(room: str = room):
        when(state(f"binary_sensor.{room}_motion").to("on"))
        service("light.turn_on", entity_id=f"light.{room}")
"""

KITCHEN_REPLACEMENT = """\
from hassle import *
from hassle.registry import entities as e


@automation(id="motion_kitchen", alias="Motion light: kitchen (UI edit)")
def motion_kitchen_ui_edit():
    when(state("binary_sensor.kitchen_motion").to("on"))
    service("light.turn_on", entity_id="light.kitchen")
    service("light.turn_on", entity_id="light.extra")
"""


def test_splice_of_metaprogrammed_object_appends_and_warns(tmp_path: Path) -> None:
    writer = SplicingSourceWriter(updated_on="2026-07-05")
    target = tmp_path / "rooms.py"
    target.write_text(LOOP_GENERATED_ROOMS, encoding="utf-8")

    writer.splice_object(target, "automation:motion_kitchen", KITCHEN_REPLACEMENT)

    after = target.read_text(encoding="utf-8")
    # No edit is silently lost: the loop is untouched, the UI edit is
    # appended, nothing is lost.
    assert "for room in ROOMS:" in after
    assert "def motion_kitchen_ui_edit():" in after
    assert "# hassle: updated from UI on 2026-07-05" in after

    assert len(writer.reconcile_warnings) == 1
    warning = writer.reconcile_warnings[0]
    assert "automation:motion_kitchen" in warning
    assert "metaprogramming" in warning.lower()
    assert "fold" in warning.lower()
    assert "extract" in warning.lower()
    assert "delete" in warning.lower()
    assert "validate" in warning.lower()


def test_splice_of_a_genuinely_stale_manifest_entry_does_not_warn(tmp_path: Path) -> None:
    # Ordinary stale-manifest append (object simply isn't defined anywhere in
    # this file, not because of a loop) -- must NOT be misdiagnosed as a
    # metaprogramming reconcile situation.
    writer = SplicingSourceWriter(updated_on="2026-07-05")
    target = _write(tmp_path)  # TWO_AUTOMATIONS, no closet automation at all

    writer.splice_object(target, "automation:closet_light_on_motion", HALL_REPLACEMENT)

    assert writer.reconcile_warnings == []


def test_reconcile_warnings_reset_per_writer_instance(tmp_path: Path) -> None:
    # A fresh writer (one per `hassle pull` invocation, per the CLI wiring)
    # starts with no accumulated warnings.
    writer = SplicingSourceWriter(updated_on="2026-07-05")
    assert writer.reconcile_warnings == []


# ---------------------------------------------------------------------------
# `find_object_statement_name`'s fallback must never match a statement that
# declares a DIFFERENT object: the plain
# name-equals-identity fallback exists for object forms the resolver doesn't
# model, not for statements it DOES model whose identity simply differs --
# matching those would splice over (or delete) the wrong object. Reachable
# only from a manifest already inconsistent with the file, where the safe
# outcome is "not found" (append / noop), never a mis-splice.
# ---------------------------------------------------------------------------


def test_fallback_never_matches_a_def_with_a_conflicting_id() -> None:
    from hassle.decompiler.splice import find_object_statement_name

    source = (
        "from hassle import automation\n"
        "\n"
        "\n"
        '@automation(id="bar", alias="Bar")\n'
        "def foo():\n"
        "    pass\n"
    )
    # `foo` IS the def's name, but the def declares automation:bar -- looking
    # up automation:foo must not hijack it.
    assert find_object_statement_name(source, "automation:foo") is None
    assert find_object_statement_name(source, "automation:bar") == "foo"


def test_fallback_never_matches_a_def_of_another_kind() -> None:
    from hassle.decompiler.splice import find_object_statement_name

    source = "from hassle import script\n\n\n@script(alias='Foo')\ndef foo():\n    pass\n"
    assert find_object_statement_name(source, "automation:foo") is None
    assert find_object_statement_name(source, "script:foo") == "foo"


def test_fallback_never_matches_a_helper_with_a_conflicting_id() -> None:
    from hassle.decompiler.splice import find_object_statement_name

    source = 'from hassle import input_boolean\n\nfoo = input_boolean(id="bar")\n'
    assert find_object_statement_name(source, "input_boolean:foo") is None
    assert find_object_statement_name(source, "input_boolean:bar") == "foo"


def test_fallback_still_matches_unmodeled_statement_forms() -> None:
    from hassle.decompiler.splice import find_object_statement_name

    # A plain assignment that isn't a modeled object-declaration call: the
    # name fallback is exactly for these.
    source = "foo = make_something()\n"
    assert find_object_statement_name(source, "automation:foo") == "foo"


# ---------------------------------------------------------------------------
# Two defs may legally share a NAME while declaring different ids (identity is
# the `id=` kwarg; the def name is arbitrary -- both compile, each registering
# under its own id). Regression: the splice/remove
# transformers matched EVERY top-level statement with the target's name, so on
# such a file a refresh spliced the target over BOTH defs (destroying the
# sibling's source) and a drop removed BOTH -- leaving only imports, which
# `delete_object` then unlinked, silently losing the still-live sibling (no
# edit is ever silently lost;
# the next push would have deleted it from HA too). Targeting must go by the
# statement's declared (kind, identity), never by name alone.
# ---------------------------------------------------------------------------

SHARED_NAME_AUTOMATIONS = """\
from hassle import automation, service, state, when


@automation(id="hall_light_on_motion", alias="Hallway light on motion")
def light_on_motion():
    when(state("binary_sensor.hall_motion").to("on"))
    service("light.turn_on", target={"entity_id": "light.hallway"})


# Keep me: hand-written note on the porch variant.
@automation(id="porch_light_on_motion", alias="Porch light on motion")
def light_on_motion():
    when(state("binary_sensor.porch_motion").to("on"))
    service("light.turn_on", target={"entity_id": "light.porch"})
"""

PORCH_VARIANT_BLOCK = (
    "# Keep me: hand-written note on the porch variant.\n"
    '@automation(id="porch_light_on_motion", alias="Porch light on motion")\n'
    "def light_on_motion():\n"
    '    when(state("binary_sensor.porch_motion").to("on"))\n'
    '    service("light.turn_on", target={"entity_id": "light.porch"})\n'
)


def test_delete_targets_by_identity_when_def_names_collide(tmp_path: Path) -> None:
    writer = SplicingSourceWriter(updated_on="2026-07-05")
    target = _write(tmp_path, SHARED_NAME_AUTOMATIONS)

    writer.delete_object(target, "automation:hall_light_on_motion")

    assert target.exists()  # name-based removal dropped BOTH defs, then the file
    after = target.read_text(encoding="utf-8")
    assert PORCH_VARIANT_BLOCK in after, after
    assert 'id="hall_light_on_motion"' not in after


def test_delete_targets_by_identity_even_for_the_second_name_collision(tmp_path: Path) -> None:
    # Deleting the SECOND of the two same-named defs: first-match-by-name is
    # just as wrong as all-matches-by-name.
    writer = SplicingSourceWriter(updated_on="2026-07-05")
    target = _write(tmp_path, SHARED_NAME_AUTOMATIONS)

    writer.delete_object(target, "automation:porch_light_on_motion")

    after = target.read_text(encoding="utf-8")
    assert 'id="hall_light_on_motion"' in after, after
    assert 'id="porch_light_on_motion"' not in after


def test_splice_targets_by_identity_when_def_names_collide(tmp_path: Path) -> None:
    writer = SplicingSourceWriter(updated_on="2026-07-05")
    target = _write(tmp_path, SHARED_NAME_AUTOMATIONS)

    writer.splice_object(target, "automation:hall_light_on_motion", HALL_REPLACEMENT)

    after = target.read_text(encoding="utf-8")
    # Name-based splicing replaced BOTH defs with the hall replacement.
    assert after.count('id="hall_light_on_motion"') == 1, after
    assert "Hallway light on motion (UI edit)" in after
    assert PORCH_VARIANT_BLOCK in after, after
