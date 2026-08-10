"""The pull engine — `apply_pull` — DESIGN §8.3.

`hassle pull` computes the same three-way plan as push and applies only the
*bundle-side* actions: `refresh` splices the UI's edit into the existing file,
`adopt` writes a brand-new file for a UI-created object, `drop` deletes the
file for a UI-deleted object, and `conflict` writes both versions with markers
(format documented in `hassle.sync.source_writer`) plus contributes to a
summary. `noop`/`update`/`delete`/`create` are push-side actions and are never
acted on here.

The key invariant: **pull never touches the Backend.**
`apply_pull` doesn't even accept one — it can't write to HA even by accident.
"""

from __future__ import annotations

import json
from pathlib import Path

from hassle.ir.keys import BLUEPRINT_KIND
from hassle.sync.models import Conflict, Plan, PlanAction, PlanEntry
from hassle.sync.source_writer import SourceWriter, adopt_write


class PullResult:
    """Summary of a pull run: which conflicts were surfaced."""

    def __init__(self, conflicts: list[Conflict]) -> None:
        self.conflicts = conflicts


def apply_pull(plan: Plan, source_writer: SourceWriter) -> PullResult:
    """Apply the bundle-side actions of ``plan`` via ``source_writer``."""
    conflicts: list[Conflict] = []
    for entry in plan.entries:
        if entry.kind == BLUEPRINT_KIND:
            # docs/internals/blueprints-design.md §5: blueprints are excluded
            # from pull's WRITES. HA has no command that serves a blueprint's
            # source back (§2.1), so there is nothing to materialize -- an
            # `adopt` would write a file with no content and a `refresh` would
            # splice a metadata body over an authored document. A remote-only
            # blueprint is still visible: `compute_plan` gives it the
            # `adopt (unmanageable)` warning row (§3), whose message says what
            # a human has to do by hand.
            #
            # Excluded from writes, NOT from the report: a conflict still has
            # to reach the user, so the CONFLICT branch's `conflicts.append`
            # below is deliberately reproduced here.
            if entry.action is PlanAction.CONFLICT and entry.conflict is not None:
                conflicts.append(entry.conflict)
            continue
        if entry.action is PlanAction.REFRESH:
            _refresh(entry, source_writer)
        elif entry.action is PlanAction.ADOPT:
            _adopt(entry, source_writer)
        elif entry.action is PlanAction.DROP:
            _drop(entry, source_writer)
        elif entry.action is PlanAction.CONFLICT:
            _write_conflict(entry, source_writer)
            if entry.conflict is not None:
                conflicts.append(entry.conflict)
        # NOOP / UPDATE / DELETE / CREATE: push-side or no-op; pull ignores them.
    return PullResult(conflicts=conflicts)


def _placeholder_dsl_source(object_key: str, config: dict[str, object] | None) -> str:
    """A stub "DSL source" string standing in for the real decompiler
    (`hassle.decompiler`; see `hassle.sync.pull_apply` for the real
    integration).

    Not real Python — just enough for the pull engine's *action* (splice vs.
    write vs. delete, with the right object key and config data) to be under
    test.
    """
    body = json.dumps(config, indent=2, sort_keys=True) if config is not None else "null"
    return f"# hassle: decompiled from {object_key}\n# {body}\n"


def _refresh(entry: PlanEntry, source_writer: SourceWriter) -> None:
    path = Path(entry.source_path or f"{entry.object_key.replace(':', '_')}.py")
    content = _placeholder_dsl_source(entry.object_key, entry.remote)
    source_writer.splice_object(path, entry.object_key, content)


def _adopt(entry: PlanEntry, source_writer: SourceWriter) -> None:
    path = Path(entry.source_path or f"{entry.object_key.replace(':', '_')}.py")
    content = _placeholder_dsl_source(entry.object_key, entry.remote)
    # ADOPT never clobbers a file that already has real content at this
    # object's default placement (docs/internals/dashboards-design.md §7,
    # docs/internals/sync.md) -- kind-generic, `hassle.sync.source_writer.adopt_write`.
    adopt_write(source_writer, path, entry.object_key, content)


def _drop(entry: PlanEntry, source_writer: SourceWriter) -> None:
    path = Path(entry.source_path or f"{entry.object_key.replace(':', '_')}.py")
    source_writer.delete_object(path, entry.object_key)


def _write_conflict(entry: PlanEntry, source_writer: SourceWriter) -> None:
    path = Path(entry.source_path or f"{entry.object_key.replace(':', '_')}.py")
    conflict = entry.conflict
    local_value = conflict.local if conflict else entry.local
    remote_value = conflict.remote if conflict else entry.remote
    local_body = json.dumps(local_value, indent=2, sort_keys=True)
    remote_body = json.dumps(remote_value, indent=2, sort_keys=True)
    content = (
        f"# hassle: CONFLICT on {entry.object_key} -- resolve with "
        f"--accept-local/--accept-remote or edit and re-run `hassle push`\n"
        "<<<<<<< local\n"
        f"{local_body}\n"
        "=======\n"
        f"{remote_body}\n"
        ">>>>>>> remote\n"
    )
    source_writer.write_whole_file(path, content)
