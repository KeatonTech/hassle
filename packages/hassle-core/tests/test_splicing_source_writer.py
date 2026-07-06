"""`SplicingSourceWriter` — M2's LibCST splicer wired into the F2 seam.

Regression companion to `hassle-cli/tests/test_pull_refresh_splice.py` (pull's
REFRESH clobbered sibling objects sharing a source file, because the CLI used
`WholeFileSourceWriter`'s documented whole-file stand-in): a real
`SourceWriter` whose `splice_object` surgically replaces one object's
statement (and whose `delete_object` surgically removes one), leaving every
sibling statement and hand-written comment untouched (I6).
"""

from __future__ import annotations

from pathlib import Path

from hassle.sync.source_writer import SourceWriter, SplicingSourceWriter

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
    # in -- the siblings must survive (I6); the refreshed def is appended.
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
