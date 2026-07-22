"""CLI-driven pull-side apply, using the real decompiler for `refresh`/`adopt`
content (DESIGN §8.3).

`hassle.sync.pull.apply_pull` hardcodes a JSON-comment placeholder for
`refresh`/`adopt` content -- explicitly documented as a stand-in for a real
`SourceWriter` implementation (docs/internals/backend-protocol.md). This module is that
implementation: it re-implements `apply_pull`'s action dispatch, but with
real decompiled DSL source (`hassle.decompiler.decompile_bundle`) instead of
the placeholder, while keeping the exact same conflict-marker format
(docs/internals/backend-protocol.md's `<<<<<<< local` block) so a conflict written by this CLI
looks identical to one written by `RecordingSourceWriter`-based unit tests.

Before any ADOPT destination is written, `apply_pull_with_decompiler` runs a
**batch-level self-check**: it materializes every adopt batch's decompiled
output together into one isolated temp directory and compiles that whole
tree once, then recompiles every adopted/refreshed object and compares it
against the original stored config it was decompiled from (comparing
canonical-JSON values, not decompiled text). See docs/internals/sync.md for
why the self-check is batch-level rather than per-file, why cross-file
script-call rewrites are handled the way they are, and why the value
comparison must not go through decompiled text.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

import libcst as cst

from hassle.compiler.bundle import compile_bundle
from hassle.decompiler.codegen import ScriptRef, decompile_bundle
from hassle.ir.canonical import sha256_hash
from hassle.ir.models import IRObject, parse
from hassle.ir.modernize import modernize_for_comparison
from hassle.sync.models import Conflict, Plan, PlanAction, PlanEntry
from hassle.sync.pull import PullResult
from hassle.sync.source_writer import SourceWriter

if TYPE_CHECKING:
    from hassle.registry.snapshot import RegistrySnapshot


class DecompiledBatchDoesNotCompileError(Exception):
    """Raised by the pre-write batch-level self-check (module docstring) when
    the adopted files' freshly decompiled source doesn't compile as a whole
    -- a Hassle decompiler bug, never a user mistake (the input was real,
    already-stored HA config the decompiler itself just produced source
    for). Carries a what/where/fix message naming every destination path
    involved; the CLI layer (`hassle_cli.cli.pull`) also has its own
    whole-bundle backstop as a second line of defense for anything this
    earlier, narrower check can't see (module docstring: `_refresh`'s
    cross-file case, where the callee's file isn't part of this pull at all).

    Also raised when the batch DOES compile but a recompiled object's
    canonical value differs from the original stored config it was
    decompiled from -- a silent decompiler coordination bug (see
    docs/internals/sync.md) is exactly as serious as a raised exception, and
    must not reach disk either.
    """

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
            "https://github.com/KeatonTech/hassle/issues; nothing has been written "
            "for these destinations yet."
        )


class DecompiledValueMismatchError(Exception):
    """Raised by the pre-write batch-level self-check when a recompiled
    object's canonical-JSON value (:func:`values_match`) does not reproduce
    the ORIGINAL stored config it was decompiled from, modulo the bounded,
    deterministic modernizations a decompile+recompile cycle is expected to
    apply. Unlike :class:`DecompiledBatchDoesNotCompileError` (raised on an
    exception), this catches a decompiler bug that compiles cleanly but
    silently changes the object's meaning -- e.g. a `for_each`
    template-string bug where `list("{{ ... }}")` never raises, so only a
    value comparison, not "did it compile", can catch it. The comparison is
    CONTEXT-FREE (canonical-JSON values, never decompiled DSL text) -- see
    docs/internals/sync.md for why a text-based comparison would produce
    false positives. Never a user mistake: the input was real, already-stored
    HA config."""

    def __init__(self, object_keys: list[str]) -> None:
        self.object_keys = object_keys
        keys = ", ".join(sorted(object_keys))
        super().__init__(
            f"the bundle content about to be written does not reproduce the original stored "
            f"configuration for object(s): {keys} (it compiles, but recompiling the decompiled "
            "source yields a different value). This is a bug in Hassle's decompiler, not a "
            "mistake in your HA configuration. Fix: please report this (include the object(s) "
            "listed) at https://github.com/KeatonTech/hassle/issues; nothing has been "
            "written for these destinations yet."
        )


def _entry_path(entry: PlanEntry) -> Path:
    return Path(entry.source_path or f"{entry.object_key.replace(':', '_')}.py")


def _parsed(object_key: str, config: dict[str, Any]) -> Any:
    kind = object_key.partition(":")[0]
    identity = object_key.partition(":")[2]
    return parse(config, kind=kind, key_hint=identity)


def _decompiled_source(
    object_key: str,
    config: dict[str, Any],
    script_refs: dict[str, ScriptRef] | None = None,
    *,
    snapshot: RegistrySnapshot | None = None,
) -> str:
    return decompile_bundle(
        {object_key: _parsed(object_key, config)}, script_refs=script_refs, snapshot=snapshot
    )


def _refresh(
    entry: PlanEntry, source_writer: SourceWriter, *, snapshot: RegistrySnapshot | None = None
) -> None:
    assert entry.remote is not None
    # No script_refs here -- see module docstring: a single-object LibCST
    # splice cannot also inject a new top-level import line for the CROSS-FILE
    # script-call rewrite. `snapshot` is different: any
    # `from hassle.services import <domain>` import the namespace form needs
    # is emitted as part of THIS SAME single-object decompile's own header
    # (never a separate top-level statement to splice in), so
    # `SplicingSourceWriter.splice_object`'s existing `merge_missing_imports`
    # seam (which already merges the `_ENTITIES_IMPORT_LINE`/star-import
    # header on a fresh file) merges it into an existing file the identical
    # way -- this is safe on the splice path where the cross-file script-call
    # import is not.
    source_writer.splice_object(
        _entry_path(entry),
        entry.object_key,
        _decompiled_source(entry.object_key, entry.remote, snapshot=snapshot),
    )


# Mirrors `hassle.decompiler.codegen._automation_source`'s own
# `_ALLOWED_TOP_LEVEL` gate (the set of top-level keys a typed `@automation`
# can express at all -- anything else forces the whole-object `raw_automation`
# fallback, DESIGN §5.8), widened with the legacy SINGULAR block-key spellings
# (`trigger`/`condition`/`action`) since `values_match` checks ``original``
# BEFORE `normalize_ha` pluralizes them (`codegen.py`'s own check runs after).
_TYPED_AUTOMATION_TOP_LEVEL_KEYS: frozenset[str] = frozenset(
    {
        "id",
        "alias",
        "description",
        "mode",
        "max",
        "max_exceeded",
        "initial_state",
        "triggers",
        "conditions",
        "actions",
        "trigger",
        "condition",
        "action",
        "trigger_variables",
        "variables",
    }
)


def values_match(recompiled: IRObject, original: dict[str, Any]) -> bool:
    """Context-free value comparison: True if ``recompiled`` (an
    already-compiled IR object) reproduces ``original`` (the raw stored
    config it was decompiled from), modulo the bounded, deterministic
    modernizations a decompile+recompile cycle is expected to apply
    (:func:`~hassle.ir.modernize.modernize_for_comparison` -- inner
    `platform:` -> `trigger:`, string/numeric `delay:` -> the dict-of-units
    form; nothing else).

    Compares CANONICAL-JSON VALUES (`sha256_hash`), never decompiled DSL text
    -- see docs/internals/sync.md for why a text comparison is NOT
    context-free: the same IR value can decompile to different Python source
    depending on what else is being decompiled alongside it (a batch-context
    name-collision `_2` suffix, a same-batch script-call rewrite), neither of
    which is a value change. This function is the single shared comparison
    both pull-side self-checks (`_self_check_adopt_batches` below, and
    `hassle_cli.cli.pull`'s post-write backstop) use, so they can never
    disagree on what counts as a mismatch.

    Two further bounded, deterministic adjustments to ``original`` before
    modernizing -- both already precedented by `test_roundtrip_corpus.py`'s own
    test-side expectation adjustment for the identical comparison, and both
    artifacts of hand-authored docs-example fixtures rather than anything a
    real HA install ever actually stores (real HA always returns `id` and
    always returns all three block keys, even empty -- these only arise via
    `FakeBackend`-seeded corpus fixtures in tests):

    - An automation ``original`` with no ``id`` at all gets ``recompiled.identity``
      backfilled (the compiler always materializes an explicit ``id`` --
      `options.get("id") or func.__name__`, docs/internals/ha-api-notes.md -- so a
      stored automation missing `id` entirely only ever arises from a
      docs-example fixture whose identity is extrinsic, a ``key_hint``).
    - A TYPED ``@automation`` always materializes ``triggers``/``conditions``/
      ``actions``, even empty (bundle.py's `_build_automation`) -- ``original``
      missing one of these three keys gets it defaulted to ``[]``, but ONLY
      when ``original``'s own top-level keys are all typed-automation-
      expressible (:data:`_TYPED_AUTOMATION_TOP_LEVEL_KEYS`, mirroring
      `hassle.decompiler.codegen._automation_source`'s own gate). An object
      whose top-level shape forces the whole-object `raw_automation` fallback
      (DESIGN §5.8 -- e.g. the ancient inline `platform:`/`entity_id:`/`to:`
      form with no `trigger:`/`triggers:` wrapper at all,
      `automation_legacy_platform_naming.json`) preserves its body VERBATIM,
      with no materialized empty blocks at all -- defaulting one in for it
      would be exactly the false positive this fix removes, just from the
      other direction (adding a key that was never really implied).

    Neither adjustment mutates the caller's ``original``.
    """
    comparable_original: dict[str, Any] = original
    if recompiled.kind() == "automation":
        if "id" not in comparable_original:
            comparable_original = {**comparable_original, "id": recompiled.identity}
        if set(comparable_original) <= _TYPED_AUTOMATION_TOP_LEVEL_KEYS:
            # Check BOTH spellings (`trigger`/`triggers`, ...) -- `original` may
            # still be in the legacy singular schema at this point (this runs
            # before `modernize_for_comparison`'s own `normalize_ha` call), so
            # defaulting on the plural spelling alone would add a SECOND,
            # conflicting key alongside an already-present singular one.
            for singular, plural in (
                ("trigger", "triggers"),
                ("condition", "conditions"),
                ("action", "actions"),
            ):
                if singular not in comparable_original and plural not in comparable_original:
                    comparable_original = {**comparable_original, plural: []}
    return sha256_hash(
        modernize_for_comparison(comparable_original, kind=recompiled.kind())
    ) == sha256_hash(recompiled.to_ha())


def _self_check_adopt_batches(
    batch_sources: dict[Path, str],
    object_keys: list[str],
    original_configs: dict[str, dict[str, Any]],
) -> None:
    """Compile EVERY adopt batch's decompiled output together, in one
    isolated temp directory using the real relative destination paths,
    before any of them is actually written (module docstring: the
    batch-level self-check; see docs/internals/sync.md for why). Materializing
    them all together (not one file in isolation) is what lets a cross-file
    import between two objects BOTH being freshly adopted in this same pull
    resolve correctly, instead of false-positiving on `ModuleNotFoundError`
    for a sibling file this check simply hadn't written yet. Raises
    :class:`DecompiledBatchDoesNotCompileError` on failure, naming every
    destination path and object key involved -- nothing has been written to
    the real bundle yet.

    ``original_configs``: every recompiled object is ALSO compared against
    the ORIGINAL stored config it was decompiled from, via
    :func:`values_match` -- "does it compile" alone cannot catch a decompiler
    bug that compiles cleanly but silently changes an object's meaning
    (`list("{{ template }}")` never raises), and a decompiled-TEXT comparison
    is not context-free (see docs/internals/sync.md).
    :class:`DecompiledValueMismatchError` is raised for a genuine mismatch,
    naming every object_key whose value changed.
    """
    if not batch_sources:
        return
    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        for path, source in batch_sources.items():
            dest = tmp_root / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(source, encoding="utf-8")
        try:
            result = compile_bundle(tmp_root)
        except Exception as exc:
            raise DecompiledBatchDoesNotCompileError(list(batch_sources), object_keys, exc) from exc

        mismatched: list[str] = []
        for object_key, original in original_configs.items():
            recompiled = result.objects.get(object_key)
            if recompiled is None:
                continue  # not part of this self-check's batch
            if not values_match(recompiled, original):
                mismatched.append(object_key)
        if mismatched:
            raise DecompiledValueMismatchError(sorted(mismatched))


def _merge_adopt_batch_into_existing(existing_source: str, batch_source: str) -> str:
    """Append an ADOPT batch's decompiled objects to an ALREADY-EXISTING
    destination file, preserving every statement already there -- no local or
    UI edit is ever silently lost. Writing the whole file instead
    (`write_whole_file`) on an existing `misc.py` would silently drop every
    pre-existing uncategorized object while the manifest kept tracking them,
    so the very next `hassle plan` would propose a DELETE for each one
    against live HA.

    Same building blocks as `SplicingSourceWriter.splice_object`'s append
    path (`hassle.decompiler.splice`): the batch module is split into its
    import header and object statements, the objects are appended after the
    existing content (two blank lines, the decompiler's own top-level
    spacing), and whichever header imports the file doesn't already satisfy
    are merged in after its last import. The existing content is never
    reformatted or reordered -- hand-written comments and spacing survive
    byte-for-byte, exactly like a REFRESH splice (DESIGN §7.3 test 4).

    A freshly-decompiled def whose name collides with an existing def in the
    file is legal (identity lives in the decorator's ``id=``, and both
    register at decoration time -- `hassle.decompiler.splice`'s own
    name-collision regressions cover targeting them independently), so no
    dedup against existing names is needed for correctness.
    """
    from hassle.decompiler.splice import merge_missing_imports, split_module_source

    import_sources, object_sources = split_module_source(batch_source)
    appended = existing_source.rstrip("\n") + "\n\n\n" + "".join(object_sources).strip("\n") + "\n"
    return merge_missing_imports(appended, import_sources)


def _adopt_batch_source(
    entries: list[PlanEntry],
    script_refs: dict[str, ScriptRef] | None,
    *,
    snapshot: RegistrySnapshot | None = None,
) -> tuple[Path, str]:
    """Decompile all ADOPTs destined for one file into ONE multi-object
    module, without writing it (per-object whole-file writes were
    last-writer-wins: adopting N new objects of a kind left only the final
    one on disk -- one real pull adopted 101 objects into a shared
    destination and only 3 survived to the next read; ``decompile_bundle``
    natively emits multi-object modules, so batching is also the natural
    codegen shape). Source-only (no write) so `apply_pull_with_decompiler`
    can self-check every destination together before any of them is written
    (module docstring; see docs/internals/sync.md for why).

    ``snapshot``: threaded straight through to
    ``decompile_bundle`` -- a whole-file ADOPT batch can safely gain the new
    ``from hassle.services import <domains>`` header line (unlike `_refresh`'s
    single-object splice, a fresh whole-file write has no existing content to
    merge into)."""
    path = _entry_path(entries[0])
    objs = {e.object_key: _parsed(e.object_key, e.remote) for e in entries if e.remote is not None}
    return path, decompile_bundle(objs, script_refs=script_refs, snapshot=snapshot)


def _insert_category_global(source: str, category_name: str) -> str:
    """Insert ``CATEGORY = "<category_name>"`` right after ``source``'s
    import header -- pull emits the global when it CREATES a brand-new
    category file. Only ever called for a fresh ADOPT-batch destination that
    doesn't exist on disk yet -- an existing file's `CATEGORY` line is left
    alone entirely by the splicer (`hassle.decompiler.splice`'s
    `splice_object`/`remove_object` only ever touch the ONE statement
    matching a given object key; a plain `CATEGORY = "..."` assignment is
    never recognized as an object statement at all, so REFRESH/DROP simply
    never look at it).

    Implemented with LibCST (already a decompiler-layer dependency) rather
    than string surgery, so the inserted statement is always syntactically
    well-formed regardless of what ``source`` looks like; a `ruff format`
    pass afterward keeps spacing byte-stable and consistent with
    `decompile_bundle`'s own formatting (deterministic output).
    """
    module = cst.parse_module(source)
    last_import_index = -1
    for index, stmt in enumerate(module.body):
        is_import = isinstance(stmt, cst.SimpleStatementLine) and all(
            isinstance(small, (cst.Import, cst.ImportFrom)) for small in stmt.body
        )
        if is_import:
            last_import_index = index
    category_stmt = cst.parse_statement(f"CATEGORY = {category_name!r}\n").with_changes(
        leading_lines=[cst.EmptyLine(), cst.EmptyLine()]
    )
    new_body = list(module.body)
    new_body.insert(last_import_index + 1, category_stmt)
    new_source = module.with_changes(body=new_body).code
    # Shared resolver: a bare "ruff" here
    # crashes standalone tool installs where the binary lives in the venv's
    # bin dir, not on PATH -- exactly the bug codegen._format_with_ruff guards against.
    from hassle.decompiler.codegen import _format_with_ruff  # pyright: ignore[reportPrivateUsage]

    return _format_with_ruff(new_source)


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
    """The cross-reference table for this whole
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


def apply_pull_with_decompiler(
    plan: Plan,
    source_writer: SourceWriter,
    *,
    category_display_names: dict[str, str] | None = None,
    snapshot: RegistrySnapshot | None = None,
) -> PullResult:
    """Same action dispatch as `hassle.sync.pull.apply_pull`, but real
    decompiled DSL content for `refresh`/`adopt` instead of the placeholder.

    ``category_display_names`` (additive): bundle-relative
    destination path -> the HA category's real display name (`hassle_cli.
    bundle_ops`/`cli.py`'s pull command builds this from the registry
    snapshot -- the same real name `bundle_ops._category_source_path`
    already slugifies for placement, never thrown away here). Only ever
    consulted for an ADOPT batch whose destination file does NOT already
    exist on disk -- i.e. pull is CREATING that category file for the first
    time. Adopting a further object into an ALREADY-EXISTING file (category
    file or the shared `misc.py`) never re-emits or duplicates the global:
    the batch is MERGED into the existing content
    (:func:`_merge_adopt_batch_into_existing` -- append the decompiled
    objects, merge missing header imports, touch nothing else), so the
    file's existing `CATEGORY` line, objects, and hand-written comments all
    survive -- no local or UI edit is ever silently lost.

    ``snapshot``: the same registry snapshot `cli.py`'s pull
    command already refreshes every pull -- threaded through to every
    `decompile_bundle` call this function makes, so a plain service-call
    action decompiles to the typed namespace form when the snapshot confirms
    the service exists (falls back to `service(...)` when `None`).
    """
    script_refs = _script_refs_for_plan(plan)
    conflicts: list[Conflict] = []
    adopts_by_path: dict[Path, list[PlanEntry]] = {}
    conflict_blocks_by_path: dict[Path, list[str]] = {}
    for entry in plan.entries:
        if entry.action is PlanAction.REFRESH:
            _refresh(entry, source_writer, snapshot=snapshot)
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
    # together (module docstring; see docs/internals/sync.md for why), THEN
    # write -- so a decompiler coordination bug is caught before any adopted
    # file lands on disk, with cross-file imports between two objects both
    # being adopted in this same pull resolving correctly (not checked one
    # file at a time).
    batch_sources: dict[Path, str] = {}
    all_object_keys: list[str] = []
    original_configs: dict[str, dict[str, Any]] = {}
    for path, entries in adopts_by_path.items():
        batch_path, source = _adopt_batch_source(entries, script_refs, snapshot=snapshot)
        assert batch_path == path
        # Emit CATEGORY only for a file that doesn't exist
        # yet (pull is creating it) and only when a real display name is
        # known for this exact destination path.
        if category_display_names is not None and not path.exists():
            display_name = category_display_names.get(path.as_posix())
            if display_name is not None:
                source = _insert_category_global(source, display_name)
        batch_sources[path] = source
        all_object_keys.extend(e.object_key for e in entries)
        for e in entries:
            if e.remote is not None:
                original_configs[e.object_key] = e.remote
    _self_check_adopt_batches(batch_sources, sorted(all_object_keys), original_configs)
    for path, source in batch_sources.items():
        # An ALREADY-EXISTING destination (the shared uncategorized `misc.py`
        # is the canonical case: every uncategorized UI object ever created
        # adopts into it) is MERGED into, never overwritten -- a whole-file
        # write here would silently drop every pre-existing object in the
        # file while the manifest kept tracking them, so the next `hassle
        # plan` would propose a DELETE for each one (no local or UI edit is
        # ever silently lost). The self-check above already validated the
        # decompiled batch standalone; the merged file is covered by the
        # CLI's post-write whole-bundle backstop (`hassle_cli.cli.pull`),
        # which sees it exactly as the next compile will.
        if path.exists():
            source = _merge_adopt_batch_into_existing(path.read_text(encoding="utf-8"), source)
        source_writer.write_whole_file(path, source)

    for path, blocks in conflict_blocks_by_path.items():
        source_writer.write_whole_file(path, "\n".join(blocks))
    return PullResult(conflicts=conflicts)
