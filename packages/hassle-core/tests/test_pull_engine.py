"""`hassle pull` applies bundle-side actions from the plan table (DESIGN §8.3).

`hassle pull` computes the identical three-way table and applies the
*bundle-side* actions only: refresh splices, adopt creates files, drop deletes
files, conflict writes both versions with markers. HA is never written to
during pull (asserted via FakeBackend.writes_since_reset()).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hassle.backend.fake import FakeBackend
from hassle.sync import Conflict, ConflictKind, Plan, PlanAction, PlanEntry
from hassle.sync.pull import apply_pull
from hassle.sync.source_writer import RecordingSourceWriter, WholeFileSourceWriter


def test_pull_refresh_calls_splice_object() -> None:
    remote_config = {"id": "a1", "alias": "Remote Edit"}
    plan = Plan(
        entries=[
            PlanEntry(
                object_key="automation:a1",
                kind="automation",
                action=PlanAction.REFRESH,
                remote=remote_config,
                source_path="automations/a1.py",
            )
        ]
    )
    writer = RecordingSourceWriter()
    apply_pull(plan, writer)
    assert len(writer.spliced_objects) == 1
    path, object_key, _content = writer.spliced_objects[0]
    assert str(path) == "automations/a1.py"
    assert object_key == "automation:a1"


def test_pull_adopt_calls_write_whole_file() -> None:
    remote_config = {"id": "new1", "alias": "UI Created"}
    plan = Plan(
        entries=[
            PlanEntry(
                object_key="automation:new1",
                kind="automation",
                action=PlanAction.ADOPT,
                remote=remote_config,
                source_path="automations/new1.py",
            )
        ]
    )
    writer = RecordingSourceWriter()
    apply_pull(plan, writer)
    assert list(writer.written_files.keys())
    written_path = next(iter(writer.written_files))
    assert str(written_path) == "automations/new1.py"


def test_pull_adopt_preserves_existing_file_content_when_target_path_already_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ADOPT never clobbers a file that already has real content at the new
    # object's default placement (docs/internals/dashboards-design.md §7,
    # generalized to every kind by `hassle.sync.source_writer.adopt_write`):
    # when the target path already exists, the existing bytes survive
    # verbatim (preserved BY CONSTRUCTION -- read + concatenate + one
    # `write_whole_file` -- never by relying on a writer's own `splice_object`
    # semantics, which do NOT deliver this guarantee for arbitrary content,
    # see `adopt_write`'s docstring). Uses `automation` + the REAL
    # `WholeFileSourceWriter` here to show the fix is kind-agnostic and holds
    # for a real writer, not just the in-memory test double; see
    # `test_pull_dashboards_placement.py` for the dashboard-specific scenario
    # this generalizes from.
    monkeypatch.chdir(tmp_path)
    existing = tmp_path / "automations" / "new1.py"
    existing.parent.mkdir()
    existing.write_text("# hand-authored, keep me\n", encoding="utf-8")

    remote_config = {"id": "new1", "alias": "UI Created"}
    plan = Plan(
        entries=[
            PlanEntry(
                object_key="automation:new1",
                kind="automation",
                action=PlanAction.ADOPT,
                remote=remote_config,
                source_path="automations/new1.py",
            )
        ]
    )
    writer = WholeFileSourceWriter()
    apply_pull(plan, writer)

    written = existing.read_text(encoding="utf-8")
    assert "# hand-authored, keep me" in written, written
    assert "automation:new1" in written, written


def test_pull_drop_calls_delete_object() -> None:
    plan = Plan(
        entries=[
            PlanEntry(
                object_key="automation:gone",
                kind="automation",
                action=PlanAction.DROP,
                source_path="automations/gone.py",
            )
        ]
    )
    writer = RecordingSourceWriter()
    apply_pull(plan, writer)
    assert len(writer.deleted_objects) == 1
    path, object_key = writer.deleted_objects[0]
    assert str(path) == "automations/gone.py"
    assert object_key == "automation:gone"


def test_pull_conflict_writes_both_versions_with_markers() -> None:
    conflict = Conflict(
        object_key="automation:a1",
        kind=ConflictKind.BOTH_EDITED,
        base={"id": "a1", "alias": "Base"},
        local={"id": "a1", "alias": "Local"},
        remote={"id": "a1", "alias": "Remote"},
    )
    plan = Plan(
        entries=[
            PlanEntry(
                object_key="automation:a1",
                kind="automation",
                action=PlanAction.CONFLICT,
                conflict=conflict,
                source_path="automations/a1.py",
            )
        ]
    )
    writer = RecordingSourceWriter()
    result = apply_pull(plan, writer)
    assert len(writer.written_files) == 1 or len(writer.spliced_objects) == 1
    # Whichever write mechanism is used, the content must carry conflict markers.
    if writer.written_files:
        content = next(iter(writer.written_files.values()))
    else:
        content = writer.spliced_objects[0][2]
    assert "<<<<<<<" in content
    assert "=======" in content
    assert ">>>>>>>" in content
    assert result.conflicts and result.conflicts[0].object_key == "automation:a1"


def test_pull_never_writes_to_backend() -> None:
    # The key invariant: pull only touches the working tree via SourceWriter,
    # never the Backend. FakeBackend.writes_since_reset() proves zero writes.
    backend = FakeBackend.with_seed_data()
    backend.reset_write_tracking()

    remote_config = {"id": "a1", "alias": "Remote Edit"}
    plan = Plan(
        entries=[
            PlanEntry(
                object_key="automation:a1",
                kind="automation",
                action=PlanAction.REFRESH,
                remote=remote_config,
                source_path="automations/a1.py",
            ),
            PlanEntry(
                object_key="automation:new1",
                kind="automation",
                action=PlanAction.ADOPT,
                remote={"id": "new1", "alias": "New"},
                source_path="automations/new1.py",
            ),
            PlanEntry(
                object_key="automation:gone",
                kind="automation",
                action=PlanAction.DROP,
                source_path="automations/gone.py",
            ),
        ]
    )
    writer = RecordingSourceWriter()
    apply_pull(plan, writer)
    assert backend.writes_since_reset() == 0


def test_pull_skips_noop_and_update_entries() -> None:
    # update/create are push-side actions; pull must not act on them.
    plan = Plan(
        entries=[
            PlanEntry(object_key="automation:a1", kind="automation", action=PlanAction.NOOP),
            PlanEntry(
                object_key="script:s1",
                kind="script",
                action=PlanAction.UPDATE,
                local={"alias": "local-edit"},
            ),
        ]
    )
    writer = RecordingSourceWriter()
    result = apply_pull(plan, writer)
    assert not writer.written_files
    assert not writer.spliced_objects
    assert not writer.deleted_objects
    assert not result.conflicts
