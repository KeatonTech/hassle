"""The `SourceWriter` seam (docs/internals/backend-protocol.md) — DESIGN §7.3, §8.3.

`SourceWriter` decouples the sync engine's pull-side actions from the LibCST
splicer. This module covers two implementations: `WholeFileSourceWriter` (a
blunt whole-file overwrite, good enough for `adopt` and an acceptable
stand-in for `refresh`/`drop` before the splicer lands) and
`RecordingSourceWriter` (an in-memory test double used by the pull-engine tests).

Also covers the write-side containment security hardening (module docstring
of `hassle.sync.source_writer`): a destination that resolves outside the
`bundle_root` a writer was constructed with, or that is itself a symlink
(dangling or not), is refused with a what/where/fix error instead of
written. `test_splicing_source_writer.py` covers the same two checks against
`SplicingSourceWriter`'s own `splice_object`/`delete_object` overrides
(which read the destination before delegating to `write_whole_file`).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hassle.sync.source_writer import (
    RecordingSourceWriter,
    SourceWriteOutsideBundleRootError,
    SourceWriter,
    SymlinkWriteRefusedError,
    WholeFileSourceWriter,
)


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
    # Stand-in: splice_object on WholeFileSourceWriter is blunt — it overwrites
    # the whole file rather than surgically replacing one def (that's the
    # LibCST splicer's job).
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


# ---------------------------------------------------------------------------
# Write-side containment (bundle_root) -- security hardening, defense in
# depth (module docstring: remote category/entity names are slugified before
# they ever reach a path, so this isn't reachable from live HA data today,
# but the `SourceWriter` boundary is where it's enforced regardless of how
# the path was produced -- a stale manifest, or a declaration span that
# resolved outside the bundle).
# ---------------------------------------------------------------------------


def test_write_whole_file_refuses_dotdot_path_outside_bundle_root(tmp_path: Path) -> None:
    bundle_root = tmp_path / "bundle"
    bundle_root.mkdir()
    writer = WholeFileSourceWriter(bundle_root=bundle_root)
    with pytest.raises(SourceWriteOutsideBundleRootError) as excinfo:
        writer.write_whole_file(Path("../../evil.py"), "# evil\n")
    assert "evil.py" in str(excinfo.value)
    assert str(bundle_root) in str(excinfo.value)
    assert not (tmp_path.parent / "evil.py").exists()
    assert not (tmp_path / "evil.py").exists()


def test_write_whole_file_refuses_absolute_path_outside_bundle_root(tmp_path: Path) -> None:
    bundle_root = tmp_path / "bundle"
    bundle_root.mkdir()
    outside = tmp_path / "outside" / "evil.py"
    writer = WholeFileSourceWriter(bundle_root=bundle_root)
    with pytest.raises(SourceWriteOutsideBundleRootError):
        writer.write_whole_file(outside, "# evil\n")
    assert not outside.exists()


def test_write_whole_file_allows_normal_path_within_bundle_root(tmp_path: Path) -> None:
    """A normal destination -- whether given relative-to-bundle-root or
    already absolute -- must still work once a writer knows its
    `bundle_root` (the containment check is not supposed to touch legitimate
    writes)."""
    bundle_root = tmp_path / "bundle"
    bundle_root.mkdir()
    writer = WholeFileSourceWriter(bundle_root=bundle_root)

    writer.write_whole_file(Path("hallway.py"), "# ok\n")
    assert (bundle_root / "hallway.py").read_text(encoding="utf-8") == "# ok\n"

    writer.write_whole_file(bundle_root / "nested" / "porch.py", "# ok too\n")
    assert (bundle_root / "nested" / "porch.py").read_text(encoding="utf-8") == "# ok too\n"


def test_write_whole_file_with_no_bundle_root_skips_containment_check(tmp_path: Path) -> None:
    # Back-compat: most unit tests construct `WholeFileSourceWriter()` with
    # no `bundle_root` and pass an absolute `tmp_path`-rooted destination --
    # this must keep working exactly as before.
    writer = WholeFileSourceWriter()
    target = tmp_path / "elsewhere" / "hallway.py"
    writer.write_whole_file(target, "# fine\n")
    assert target.read_text(encoding="utf-8") == "# fine\n"


def test_delete_object_refuses_path_outside_bundle_root(tmp_path: Path) -> None:
    bundle_root = tmp_path / "bundle"
    bundle_root.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("# should survive\n", encoding="utf-8")
    writer = WholeFileSourceWriter(bundle_root=bundle_root)
    with pytest.raises(SourceWriteOutsideBundleRootError):
        writer.delete_object(outside, "automation:x")
    assert outside.exists()


def test_splice_object_on_whole_file_writer_refuses_path_outside_bundle_root(
    tmp_path: Path,
) -> None:
    # `WholeFileSourceWriter.splice_object` is a whole-file overwrite -- same
    # containment guarantee as `write_whole_file`, which it delegates to.
    bundle_root = tmp_path / "bundle"
    bundle_root.mkdir()
    writer = WholeFileSourceWriter(bundle_root=bundle_root)
    with pytest.raises(SourceWriteOutsideBundleRootError):
        writer.splice_object(Path("../evil.py"), "automation:x", "# evil\n")


# ---------------------------------------------------------------------------
# Write-side containment: symlinked destinations. Unconditional -- refused
# even with no `bundle_root` at all, since `Path.exists()` is `False` for a
# *dangling* symlink (the exact shape of the reported vulnerability: a
# dangling symlink committed in a bundle, e.g. `misc.py -> /outside/target`,
# fell through a naive `if path.exists(): ... else: write_text(...)` into a
# write outside the bundle).
# ---------------------------------------------------------------------------


def test_write_whole_file_refuses_dangling_symlink(tmp_path: Path) -> None:
    target = tmp_path / "misc.py"
    target.symlink_to(tmp_path / "does_not_exist" / "target.py")
    assert not target.exists()  # dangling: exists() is False
    assert target.is_symlink()  # but is_symlink() is True

    writer = WholeFileSourceWriter()
    with pytest.raises(SymlinkWriteRefusedError) as excinfo:
        writer.write_whole_file(target, "# attacker-controlled\n")
    assert "misc.py" in str(excinfo.value)
    assert not (tmp_path / "does_not_exist").exists()


def test_write_whole_file_refuses_non_dangling_symlink(tmp_path: Path) -> None:
    real_target = tmp_path / "real.py"
    real_target.write_text("# original\n", encoding="utf-8")
    link = tmp_path / "misc.py"
    link.symlink_to(real_target)
    assert link.exists()  # NOT dangling this time

    writer = WholeFileSourceWriter()
    with pytest.raises(SymlinkWriteRefusedError):
        writer.write_whole_file(link, "# attacker-controlled\n")
    # The real file the symlink pointed at must be untouched.
    assert real_target.read_text(encoding="utf-8") == "# original\n"


def test_delete_object_refuses_symlink(tmp_path: Path) -> None:
    real_target = tmp_path / "real.py"
    real_target.write_text("# original\n", encoding="utf-8")
    link = tmp_path / "misc.py"
    link.symlink_to(real_target)

    writer = WholeFileSourceWriter()
    with pytest.raises(SymlinkWriteRefusedError):
        writer.delete_object(link, "automation:x")
    assert real_target.exists()
    assert link.is_symlink()
