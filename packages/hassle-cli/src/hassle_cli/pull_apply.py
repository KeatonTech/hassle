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

**Cross-file script-call rewrite (``ux/shared-script-calls``, owner
feedback):** a caller action ``{"action": "script.<id>", ...}`` decompiles to
a real function call (with a ``from <module> import <fn>`` when the callee
lives in a different destination file) when ``<id>`` is a MANAGED script
elsewhere in this pull batch -- built once per `apply_pull_with_decompiler`
call from every REFRESH/ADOPT entry's script bodies
(``hassle_cli.bundle_ops.build_script_refs``) and threaded into every
`decompile_bundle` call below. Only `_adopt_batch`'s WHOLE-FILE writes can
safely gain a new top-level import line this way; `_refresh`'s LibCST splice
(``hassle.decompiler.splice.splice_object``) replaces exactly one top-level
statement and cannot inject a new import alongside it (module docstring:
"expected exactly one top-level statement in the replacement source") -- a
refreshed object calling a CROSS-FILE script therefore stays `service()`
there (never `raw`, no data lost, just not rewritten on that particular
code path); a same-batch call within the same splice never arises (a splice
always targets exactly one object).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hassle.decompiler.codegen import ScriptRef, decompile_bundle
from hassle.ir.models import parse
from hassle.sync.models import Conflict, Plan, PlanAction, PlanEntry
from hassle.sync.pull import PullResult
from hassle.sync.source_writer import SourceWriter


def _entry_path(entry: PlanEntry) -> Path:
    return Path(entry.source_path or f"{entry.object_key.replace(':', '_')}.py")


def _parsed(object_key: str, config: dict[str, Any]) -> Any:
    kind = object_key.partition(":")[0]
    identity = object_key.partition(":")[2]
    return parse(config, kind=kind, key_hint=identity)


def _decompiled_source(
    object_key: str, config: dict[str, Any], script_refs: dict[str, ScriptRef] | None = None
) -> str:
    return decompile_bundle({object_key: _parsed(object_key, config)}, script_refs=script_refs)


def _refresh(entry: PlanEntry, source_writer: SourceWriter) -> None:
    assert entry.remote is not None
    # No script_refs here -- see module docstring: a single-object LibCST
    # splice cannot also inject a new top-level import line.
    source_writer.splice_object(
        _entry_path(entry), entry.object_key, _decompiled_source(entry.object_key, entry.remote)
    )


def _adopt_batch(
    entries: list[PlanEntry],
    source_writer: SourceWriter,
    script_refs: dict[str, ScriptRef] | None,
) -> None:
    """All ADOPTs destined for one file become ONE multi-object module write.

    Per-object whole-file writes were last-writer-wins: adopting N new objects
    of a kind left only the final one on disk (the owner-smoke-test clobber --
    101 adopted, 3 persisted). ``decompile_bundle`` natively emits multi-object
    modules, so batching is also the natural codegen shape.
    """
    path = _entry_path(entries[0])
    objs = {e.object_key: _parsed(e.object_key, e.remote) for e in entries if e.remote is not None}
    source_writer.write_whole_file(path, decompile_bundle(objs, script_refs=script_refs))


def _drop(entry: PlanEntry, source_writer: SourceWriter) -> None:
    source_writer.delete_object(_entry_path(entry), entry.object_key)


def _conflict_block(entry: PlanEntry) -> str:
    conflict = entry.conflict
    local_value = conflict.local if conflict else entry.local
    remote_value = conflict.remote if conflict else entry.remote
    local_body = json.dumps(local_value, indent=2, sort_keys=True)
    remote_body = json.dumps(remote_value, indent=2, sort_keys=True)
    return (
        f"# hassle: CONFLICT on {entry.object_key} -- resolve with "
        f"--accept-local/--accept-remote or edit and re-run `hassle push`\n"
        "<<<<<<< local\n"
        f"{local_body}\n"
        "=======\n"
        f"{remote_body}\n"
        ">>>>>>> remote\n"
    )


def _script_refs_for_plan(plan: Plan) -> dict[str, ScriptRef]:
    """The ``ux/shared-script-calls`` cross-reference table for this whole
    pull batch: every REFRESH/ADOPT entry whose object is a managed script,
    keyed by object_id, with its destination file's placement
    (``entry.source_path``, already computed by the pull loop -- DESIGN §7.3)."""
    from hassle_cli.bundle_ops import build_script_refs

    scripts: dict[str, Any] = {}
    source_paths: dict[str, str] = {}
    for entry in plan.entries:
        if entry.action not in (PlanAction.REFRESH, PlanAction.ADOPT):
            continue
        if entry.kind != "script" or entry.remote is None or entry.source_path is None:
            continue
        scripts[entry.object_key] = entry.remote
        source_paths[entry.object_key] = entry.source_path
    return build_script_refs(scripts, source_paths)


def apply_pull_with_decompiler(plan: Plan, source_writer: SourceWriter) -> PullResult:
    """Same action dispatch as `hassle.sync.pull.apply_pull`, but real
    decompiled DSL content for `refresh`/`adopt` instead of the M5 placeholder."""
    script_refs = _script_refs_for_plan(plan)
    conflicts: list[Conflict] = []
    adopts_by_path: dict[Path, list[PlanEntry]] = {}
    conflict_blocks_by_path: dict[Path, list[str]] = {}
    for entry in plan.entries:
        if entry.action is PlanAction.REFRESH:
            _refresh(entry, source_writer)
        elif entry.action is PlanAction.ADOPT:
            adopts_by_path.setdefault(_entry_path(entry), []).append(entry)
        elif entry.action is PlanAction.DROP:
            _drop(entry, source_writer)
        elif entry.action is PlanAction.CONFLICT:
            # Conflicts sharing a destination are concatenated, same
            # rationale as _adopt_batch (never last-writer-wins).
            conflict_blocks_by_path.setdefault(_entry_path(entry), []).append(
                _conflict_block(entry)
            )
            if entry.conflict is not None:
                conflicts.append(entry.conflict)
    for _path, entries in adopts_by_path.items():
        _adopt_batch(entries, source_writer, script_refs)
    for path, blocks in conflict_blocks_by_path.items():
        source_writer.write_whole_file(path, "\n".join(blocks))
    return PullResult(conflicts=conflicts)
