"""Pull never writes a blueprint (blueprints-design §5).

HA cannot serve a blueprint's source back (§2.1), so there is nothing for pull
to materialize: an `adopt` would write a file with no content, and a `refresh`
would splice a metadata body over an authored document. The kind is excluded
from pull's writes entirely, in BOTH pull engines, and its remote-only
blueprints surface as the `adopt (unmanageable)` warning row instead (§3) so
they are at least visible.

The exclusion is structural — a kind check in the engines themselves, not a
filter every caller has to remember to apply.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from hassle.blueprints import blueprint_metadata, blueprint_remote_body
from hassle.ir import BLUEPRINT_KIND
from hassle.sync.models import Conflict, ConflictKind, Plan, PlanAction, PlanEntry
from hassle.sync.pull import apply_pull
from hassle.sync.source_writer import RecordingSourceWriter

SOURCE = """\
blueprint:
  name: Room Switch Controls
  domain: automation
  input:
    switch_entity:
actions: []
"""

PATH = "local/room-switch-controls.yaml"
KEY = f"blueprint:automation/{PATH}"


def _remote() -> dict[str, Any]:
    return blueprint_remote_body("automation", PATH, blueprint_metadata(SOURCE))


def _entry(action: PlanAction, **extra: Any) -> PlanEntry:
    return PlanEntry(
        object_key=KEY,
        kind=BLUEPRINT_KIND,
        action=action,
        source_path=f"blueprints/automation/{PATH}",
        **extra,
    )


@pytest.mark.parametrize(
    "entry",
    [
        _entry(PlanAction.ADOPT, remote=_remote(), warning=True, message="..."),
        _entry(PlanAction.REFRESH, remote=_remote()),
        _entry(PlanAction.DROP),
        _entry(
            PlanAction.CONFLICT,
            remote=_remote(),
            conflict=Conflict(
                object_key=KEY,
                kind=ConflictKind.BOTH_EDITED,
                base=None,
                local=None,
                remote=_remote(),
            ),
        ),
    ],
    ids=["adopt", "refresh", "drop", "conflict"],
)
def test_no_pull_action_writes_a_blueprint(entry: PlanEntry) -> None:
    writer = RecordingSourceWriter()
    apply_pull(Plan(entries=[entry]), writer)
    assert writer.written_files == {}
    assert writer.spliced_objects == []
    assert writer.deleted_objects == []


def test_a_blueprint_conflict_is_still_reported() -> None:
    """Excluded from WRITES, not from the report: a conflict the user has to
    resolve must stay visible even though pull cannot write either side."""
    conflict = Conflict(
        object_key=KEY,
        kind=ConflictKind.BOTH_EDITED,
        base=None,
        local=None,
        remote=_remote(),
    )
    result = apply_pull(
        Plan(entries=[_entry(PlanAction.CONFLICT, remote=_remote(), conflict=conflict)]),
        RecordingSourceWriter(),
    )
    assert result.conflicts == [conflict]


def test_other_kinds_still_pull_normally() -> None:
    """The exclusion is per-kind, not a global off switch."""
    writer = RecordingSourceWriter()
    apply_pull(
        Plan(
            entries=[
                _entry(PlanAction.ADOPT, remote=_remote(), warning=True),
                PlanEntry(
                    object_key="automation:office",
                    kind="automation",
                    action=PlanAction.ADOPT,
                    remote={"id": "office"},
                    source_path="misc.py",
                ),
            ]
        ),
        writer,
    )
    assert list(writer.written_files) == [Path("misc.py")]
    assert writer.spliced_objects == []
    assert writer.deleted_objects == []
