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
`decompile_bundle` call below. Only the ADOPT batches' WHOLE-FILE writes can
safely gain a new top-level import line this way; `_refresh`'s LibCST splice
(``hassle.decompiler.splice.splice_object``) replaces exactly one top-level
statement and cannot inject a new import alongside it (module docstring:
"expected exactly one top-level statement in the replacement source") -- a
refreshed object calling a CROSS-FILE script therefore stays `service()`
there (never `raw`, no data lost, just not rewritten on that particular
code path); a same-batch call within the same splice never arises (a splice
always targets exactly one object).

**Batch-level self-check (``ux/shared-script-calls-fix``, coordinator task 4
-- decided and documented here):** before any ADOPT destination is written,
`apply_pull_with_decompiler` materializes EVERY adopt batch's decompiled
output together into one isolated temp directory (same relative destination
paths as the real bundle) and compiles that whole tree once. A single
per-file-in-isolation check was tried first and rejected: it false-positived
on the ordinary, correct case of a script and a cross-file caller BOTH being
freshly adopted in the same pull (their destination files are siblings, but
each is meaningless compiled alone -- `ModuleNotFoundError` on the sibling's
own import, not a real bug). Compiling the whole adopted-file set together
resolves cross-file imports exactly like the real bundle would, while still
being strictly cheaper and more precise than the CLI-level whole-bundle
backstop: it fires BEFORE any file is written or the manifest is touched, and
:class:`DecompiledBatchDoesNotCompileError` names every destination path
involved. **Not** extended to `_refresh`'s single-object splice: a spliced
object's rewritten call may target a script living in a file this pull isn't
touching at all (no ADOPT/REFRESH entry for it), whose real on-disk content
isn't available to materialize here -- the CLI-level whole-bundle backstop
(`hassle_cli.cli.pull`, which runs after every write, `_refresh` included) is
the correct and sufficient backstop for that path.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from hassle.compiler.bundle import compile_bundle
from hassle.decompiler.codegen import ScriptRef, decompile_bundle
from hassle.ir.models import parse
from hassle.sync.models import Conflict, Plan, PlanAction, PlanEntry
from hassle.sync.pull import PullResult
from hassle.sync.source_writer import SourceWriter


class DecompiledBatchDoesNotCompileError(Exception):
    """Raised by the pre-write self-check (module docstring, coordinator task
    4) when the adopted files' freshly decompiled source doesn't compile as
    a whole -- a Hassle decompiler bug, never a user mistake (the input was
    real, already-stored HA config the decompiler itself just produced
    source for). Carries a what/where/fix message naming every destination
    path involved; the CLI layer (`hassle_cli.cli.pull`) also has its own
    whole-bundle backstop as a second line of defense for anything this
    earlier, narrower check can't see (module docstring: `_refresh`'s
    cross-file case, where the callee's file isn't part of this pull at all)."""

    def __init__(self, paths: list[Path], object_keys: list[str], cause: Exception) -> None:
        self.paths = paths
        self.object_keys = object_keys
        self.cause = cause
        path_list = ", ".join(str(p) for p in sorted(paths, key=str))
        keys = ", ".join(sorted(object_keys))
        super().__init__(
            f"the bundle content about to be written to [{path_list}] does not compile "
            f"({type(cause).__name__}: {cause}) -- object(s): {keys}. This is a bug in "
            "Hassle's decompiler, not a mistake in your HA configuration. Fix: please "
            "report this (include the error above and the object(s) listed) at "
            "https://github.com/hassle-project/hassle/issues; nothing has been written "
            "for these destinations yet."
        )


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


def _self_check_adopt_batches(batch_sources: dict[Path, str], object_keys: list[str]) -> None:
    """Compile EVERY adopt batch's decompiled output together, in one
    isolated temp directory using the real relative destination paths,
    before any of them is actually written (module docstring: the
    batch-level self-check, coordinator task 4). Materializing them all
    together (not one file in isolation) is what lets a cross-file import
    between two objects BOTH being freshly adopted in this same pull resolve
    correctly, instead of false-positiving on `ModuleNotFoundError` for a
    sibling file this check simply hadn't written yet. Raises
    :class:`DecompiledBatchDoesNotCompileError` on failure, naming every
    destination path and object key involved -- nothing has been written to
    the real bundle yet."""
    if not batch_sources:
        return
    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        for path, source in batch_sources.items():
            dest = tmp_root / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(source, encoding="utf-8")
        try:
            compile_bundle(tmp_root)
        except Exception as exc:
            raise DecompiledBatchDoesNotCompileError(list(batch_sources), object_keys, exc) from exc


def _adopt_batch_source(
    entries: list[PlanEntry], script_refs: dict[str, ScriptRef] | None
) -> tuple[Path, str]:
    """Decompile all ADOPTs destined for one file into ONE multi-object
    module, without writing it (per-object whole-file writes were
    last-writer-wins: adopting N new objects of a kind left only the final
    one on disk -- the owner-smoke-test clobber, 101 adopted, 3 persisted;
    ``decompile_bundle`` natively emits multi-object modules, so batching is
    also the natural codegen shape). Source-only (no write) so
    `apply_pull_with_decompiler` can self-check every destination together
    before any of them is written (module docstring, coordinator task 4)."""
    path = _entry_path(entries[0])
    objs = {e.object_key: _parsed(e.object_key, e.remote) for e in entries if e.remote is not None}
    return path, decompile_bundle(objs, script_refs=script_refs)


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
            # rationale as the ADOPT batching above (never last-writer-wins).
            conflict_blocks_by_path.setdefault(_entry_path(entry), []).append(
                _conflict_block(entry)
            )
            if entry.conflict is not None:
                conflicts.append(entry.conflict)

    # Decompile every adopt batch FIRST (no writes yet), self-check them all
    # together (module docstring, coordinator task 4), THEN write -- so a
    # decompiler coordination bug is caught before any adopted file lands on
    # disk, with cross-file imports between two objects both being adopted
    # in this same pull resolving correctly (not checked one file at a time).
    batch_sources: dict[Path, str] = {}
    all_object_keys: list[str] = []
    for path, entries in adopts_by_path.items():
        batch_path, source = _adopt_batch_source(entries, script_refs)
        assert batch_path == path
        batch_sources[path] = source
        all_object_keys.extend(e.object_key for e in entries)
    _self_check_adopt_batches(batch_sources, sorted(all_object_keys))
    for path, source in batch_sources.items():
        source_writer.write_whole_file(path, source)

    for path, blocks in conflict_blocks_by_path.items():
        source_writer.write_whole_file(path, "\n".join(blocks))
    return PullResult(conflicts=conflicts)
