"""CLI-driven pull-side apply, using M2's real decompiler for `refresh`/`adopt`
content (DESIGN §8.3).

`hassle.sync.pull.apply_pull` (M5) hardcodes a JSON-comment placeholder for
`refresh`/`adopt` content -- explicitly documented as a stand-in ("M2 will
implement `SourceWriter` for real ... at integration time", docs/backend.md).
M7 *is* that integration: this module re-implements `apply_pull`'s action
dispatch, but with real decompiled DSL source (`hassle.decompiler.
decompile_bundle`) instead of the placeholder, while keeping the exact same
conflict-marker format (docs/backend.md's `<<<<<<< local` block) so a
conflict written by this CLI looks identical to one written by
`RecordingSourceWriter`-based unit tests.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hassle.decompiler.codegen import decompile_bundle
from hassle.ir.models import parse
from hassle.sync.models import Conflict, Plan, PlanAction, PlanEntry
from hassle.sync.pull import PullResult
from hassle.sync.source_writer import SourceWriter


def _decompiled_source(object_key: str, config: dict[str, Any]) -> str:
    kind = object_key.partition(":")[0]
    identity = object_key.partition(":")[2]
    obj = parse(config, kind=kind, key_hint=identity)
    return decompile_bundle({object_key: obj})


def _refresh(entry: PlanEntry, source_writer: SourceWriter) -> None:
    assert entry.remote is not None
    path = Path(entry.source_path or f"{entry.object_key.replace(':', '_')}.py")
    source_writer.splice_object(
        path, entry.object_key, _decompiled_source(entry.object_key, entry.remote)
    )


def _adopt(entry: PlanEntry, source_writer: SourceWriter) -> None:
    assert entry.remote is not None
    path = Path(entry.source_path or f"{entry.object_key.replace(':', '_')}.py")
    source_writer.write_whole_file(path, _decompiled_source(entry.object_key, entry.remote))


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


def apply_pull_with_decompiler(plan: Plan, source_writer: SourceWriter) -> PullResult:
    """Same action dispatch as `hassle.sync.pull.apply_pull`, but real
    decompiled DSL content for `refresh`/`adopt` instead of the M5 placeholder."""
    conflicts: list[Conflict] = []
    for entry in plan.entries:
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
    return PullResult(conflicts=conflicts)
