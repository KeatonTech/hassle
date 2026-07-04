"""F2 — the `SourceWriter` seam (docs/backend.md) — DESIGN §7.3, §8.3.

`SourceWriter` decouples the sync engine's pull-side actions from M2's LibCST
splicer (a parallel, not-yet-merged branch). M5 ships two implementations:
`WholeFileSourceWriter` (a blunt whole-file overwrite, good enough for `adopt`
and an acceptable stand-in for `refresh`/`drop` until M2 lands) and
`RecordingSourceWriter` (an in-memory test double used by the pull-engine tests).
"""

from __future__ import annotations

from pathlib import Path

from hassle.sync.source_writer import RecordingSourceWriter, SourceWriter, WholeFileSourceWriter


def test_whole_file_source_writer_writes_new_file(tmp_path: Path) -> None:
    writer = WholeFileSourceWriter()
    target = tmp_path / "automations" / "hallway.py"
    writer.write_whole_file(target, "# generated\nfrom hassle import automation\n")
    assert target.read_text(encoding="utf-8") == "# generated\nfrom hassle import automation\n"


def test_whole_file_source_writer_creates_parent_dirs(tmp_path: Path) -> None:
    writer = WholeFileSourceWriter()
    target = tmp_path / "nested" / "dir" / "new_file.py"
    writer.write_whole_file(target, "content")
    assert target.exists()


def test_whole_file_source_writer_splice_overwrites_whole_file(tmp_path: Path) -> None:
    # M5 stand-in: splice_object on WholeFileSourceWriter is blunt — it overwrites
    # the whole file rather than surgically replacing one def (that's M2's job).
    writer = WholeFileSourceWriter()
    target = tmp_path / "automations" / "hallway.py"
    target.parent.mkdir(parents=True)
    target.write_text("# old content\n", encoding="utf-8")
    writer.splice_object(target, "automation:hall_light_on_motion", "# new content\n")
    assert target.read_text(encoding="utf-8") == "# new content\n"


def test_whole_file_source_writer_delete_object_removes_file(tmp_path: Path) -> None:
    writer = WholeFileSourceWriter()
    target = tmp_path / "automations" / "gone.py"
    target.parent.mkdir(parents=True)
    target.write_text("# will be dropped\n", encoding="utf-8")
    writer.delete_object(target, "automation:gone")
    assert not target.exists()


def test_whole_file_source_writer_delete_object_missing_file_is_noop(tmp_path: Path) -> None:
    writer = WholeFileSourceWriter()
    target = tmp_path / "automations" / "never_existed.py"
    writer.delete_object(target, "automation:never_existed")  # must not raise


def test_recording_source_writer_records_write_whole_file() -> None:
    writer = RecordingSourceWriter()
    writer.write_whole_file(Path("automations/new.py"), "content-a")
    assert writer.written_files[Path("automations/new.py")] == "content-a"


def test_recording_source_writer_records_splice_object() -> None:
    writer = RecordingSourceWriter()
    writer.splice_object(Path("automations/hallway.py"), "automation:hall", "spliced-src")
    assert writer.spliced_objects == [
        (Path("automations/hallway.py"), "automation:hall", "spliced-src")
    ]


def test_recording_source_writer_records_delete_object() -> None:
    writer = RecordingSourceWriter()
    writer.delete_object(Path("automations/gone.py"), "automation:gone")
    assert writer.deleted_objects == [(Path("automations/gone.py"), "automation:gone")]


def test_recording_source_writer_never_touches_disk(tmp_path: Path) -> None:
    writer = RecordingSourceWriter()
    target = tmp_path / "should_not_exist.py"
    writer.write_whole_file(target, "content")
    assert not target.exists()


def test_source_writer_is_runtime_checkable_protocol() -> None:
    assert isinstance(WholeFileSourceWriter(), SourceWriter)
    assert isinstance(RecordingSourceWriter(), SourceWriter)
