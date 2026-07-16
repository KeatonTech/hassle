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

**Self-check widened to compare VALUES, not just "does it compile"
(``ux/dsl-ergonomics``, item 4 investigation -- the more important half of the
`for_each` template-string bug fix).** The pre-existing self-check above (and
the CLI-level post-write backstop, `hassle_cli.cli.pull`) only ever asserted
that the freshly decompiled source **compiles without raising**. That is not
the same thing as `compile(decompile(x)) == x` (I3) -- a `repeat.for_each`
template STRING that the (buggy, pre-fix) decompiler/compiler pair silently
exploded into a list of individual characters compiled just fine (`list("...")`
never raises); the self-check saw a clean compile and let it through, and the
character-explosion shape survived to disk on the owner's real bundle. Both
self-checks now ALSO recompile every adopted/refreshed object and compare it
against the ORIGINAL stored `remote` config it was decompiled from --
:class:`DecompiledValueMismatchError` is raised for a value mismatch too, not
just a raised exception, with the cause message spelling out that the
recompiled value differs from the original (never a user mistake: the input
was real, already-stored HA config).

**Field failure, then fix (``fix/self-check-value-compare``, coordinator
report): decompiled-TEXT comparison was ITSELF context-dependent, causing a
false positive on the owner's live bundle.** The first attempt at the value
comparison (decompile BOTH the recompiled object and the original stored
config to DSL source and compare the TEXT -- the same technique
`hassle_cli.diffing.is_modernization_only_diff` uses on the plan side) was
wrong: decompiled TEXT is not context-free. The SAME IR value can decompile
to different Python source depending on what ELSE is being decompiled
alongside it in a real multi-object batch -- a sibling object's alias
colliding forces a `_2` function-name suffix (DESIGN §7.3's deterministic
dedup), and a same-batch script call resolves through a `CallResolver` to a
real function call instead of `service(...)` (`ux/shared-script-calls`).
Neither of those is a value change (a Python identifier and a call-site
rewrite are never part of `to_ha()`), but a text comparison sees them as
"different DSL" and raises anyway -- exactly the failure reported on the
owner's live bundle: `hassle pull` refused to write six objects (an
automation plus five helpers sharing its adopt batch), even though a direct
raw-JSON comparison showed at least three of them were byte-identical to
what was already stored. Blocking the whole batch made it worse: a
false-positive mismatch on ONE object (the automation) aborted the write of
every sibling in the same self-check call, including helpers that were never
actually wrong.

**The fix: compare canonical-JSON VALUES, never decompiled text.**
:func:`hassle.ir.modernize.modernize_for_comparison` is the bounded,
deterministic transform a decompile+recompile cycle is expected to apply --
promoted from `test_roundtrip_corpus.py`'s `_modernized` test-only helper
(inner `platform:` -> `trigger:`, and a string/numeric `delay:` -> the
dict-of-units form; nothing else) -- applied to `original` before hashing
and comparing against `recompiled.to_ha()`. This is CONTEXT-FREE by
construction: it only ever looks at the JSON value itself, so the same input
always modernizes to the same output regardless of what else is being
compiled/decompiled alongside it in a batch. See
`packages/hassle-cli/tests/test_pull_adopt_batch_self_check.py`'s regression
tests (the ORIGINAL for_each-bug true-positive case, still caught; and the
NEW false-positive case -- a batch-context name collision forcing a `_2`
suffix on one object, values identical -- now correctly passes) and
`packages/hassle-core/tests/test_ir_modernize_for_comparison.py` for the
transform itself.
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
    """Raised by the pre-write self-check (module docstring, coordinator task
    4) when the adopted files' freshly decompiled source doesn't compile as
    a whole -- a Hassle decompiler bug, never a user mistake (the input was
    real, already-stored HA config the decompiler itself just produced
    source for). Carries a what/where/fix message naming every destination
    path involved; the CLI layer (`hassle_cli.cli.pull`) also has its own
    whole-bundle backstop as a second line of defense for anything this
    earlier, narrower check can't see (module docstring: `_refresh`'s
    cross-file case, where the callee's file isn't part of this pull at all).

    Also raised (``ux/dsl-ergonomics``, item 4 investigation) when the batch
    DOES compile but a recompiled object's canonical value differs from the
    original stored config it was decompiled from -- a silent decompiler
    coordination bug (module docstring: "self-check widened to compare
    values") is exactly as serious as a raised exception, and must not reach
    disk either.
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
            "https://github.com/hassle-project/hassle/issues; nothing has been written "
            "for these destinations yet."
        )


class DecompiledValueMismatchError(Exception):
    """Raised by the pre-write self-check (``ux/dsl-ergonomics``, item 4
    investigation; comparison mechanism fixed in ``fix/self-check-value-
    compare``) when a recompiled object's canonical-JSON value (module
    docstring: :func:`values_match`) does not reproduce the ORIGINAL stored
    config it was decompiled from, modulo the bounded, deterministic
    modernizations a decompile+recompile cycle is expected to apply. Unlike
    :class:`DecompiledBatchDoesNotCompileError` (raised on an exception), this
    catches a decompiler bug that compiles cleanly but silently changes the
    object's meaning -- e.g. the `for_each` template-string bug (module
    docstring): `list("{{ ... }}")` never raises, so only a value comparison,
    not "did it compile", can catch it. The comparison is CONTEXT-FREE
    (canonical-JSON values, never decompiled DSL text) -- see the module
    docstring's "field failure, then fix" for why the earlier text-based
    comparison false-positived on the owner's live bundle. Never a user
    mistake: the input was real, already-stored HA config."""

    def __init__(self, object_keys: list[str]) -> None:
        self.object_keys = object_keys
        keys = ", ".join(sorted(object_keys))
        super().__init__(
            f"the bundle content about to be written does not reproduce the original stored "
            f"configuration for object(s): {keys} (it compiles, but recompiling the decompiled "
            "source yields a different value). This is a bug in Hassle's decompiler, not a "
            "mistake in your HA configuration. Fix: please report this (include the object(s) "
            "listed) at https://github.com/hassle-project/hassle/issues; nothing has been "
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
    # script-call rewrite. `snapshot` (MILESTONES M18) is different: any
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
    """Context-free value comparison (``fix/self-check-value-compare``,
    coordinator field-failure fix): True if ``recompiled`` (an already-compiled
    IR object) reproduces ``original`` (the raw stored config it was decompiled
    from), modulo the bounded, deterministic modernizations a decompile+
    recompile cycle is expected to apply (:func:`~hassle.ir.modernize.
    modernize_for_comparison` -- inner `platform:` -> `trigger:`, string/numeric
    `delay:` -> the dict-of-units form; nothing else).

    Compares CANONICAL-JSON VALUES (`sha256_hash`), never decompiled DSL text --
    see this module's docstring ("field failure, then fix") for why a text
    comparison is NOT context-free: the same IR value can decompile to
    different Python source depending on what else is being decompiled
    alongside it (a batch-context name-collision `_2` suffix, a same-batch
    script-call rewrite), neither of which is a value change. This function is
    the single shared comparison both pull-side self-checks
    (`_self_check_adopt_batches` below, and `hassle_cli.cli.pull`'s post-write
    backstop) use, so they can never disagree on what counts as a mismatch.

    Two further bounded, deterministic adjustments to ``original`` before
    modernizing -- both already precedented by `test_roundtrip_corpus.py`'s own
    test-side expectation adjustment for the identical comparison, and both
    artifacts of hand-authored docs-example fixtures rather than anything a
    real HA install ever actually stores (real HA always returns `id` and
    always returns all three block keys, even empty -- these only arise via
    `FakeBackend`-seeded corpus fixtures in tests):

    - An automation ``original`` with no ``id`` at all gets ``recompiled.identity``
      backfilled (the compiler always materializes an explicit ``id`` --
      `options.get("id") or func.__name__`, docs/ha-api-notes.md's M2 finding --
      so a stored automation missing `id` entirely only ever arises from a
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
    batch-level self-check, coordinator task 4). Materializing them all
    together (not one file in isolation) is what lets a cross-file import
    between two objects BOTH being freshly adopted in this same pull resolve
    correctly, instead of false-positiving on `ModuleNotFoundError` for a
    sibling file this check simply hadn't written yet. Raises
    :class:`DecompiledBatchDoesNotCompileError` on failure, naming every
    destination path and object key involved -- nothing has been written to
    the real bundle yet.

    ``original_configs`` (``ux/dsl-ergonomics``, item 4 investigation, widened
    in ``fix/self-check-value-compare``, module docstring: "the fix: compare
    canonical-JSON VALUES, never decompiled text"): every recompiled object is
    ALSO compared against the ORIGINAL stored config it was decompiled from,
    via :func:`values_match` -- "does it compile" alone cannot catch a
    decompiler bug that compiles cleanly but silently changes an object's
    meaning (`list("{{ template }}")` never raises), and a decompiled-TEXT
    comparison is not context-free (the field failure this module docstring
    documents). :class:`DecompiledValueMismatchError` is raised for a genuine
    mismatch, naming every object_key whose value changed.
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
    destination file, preserving every statement already there (I6 -- the
    BrandtCamp field failure, 2026-07-13: `write_whole_file` on an existing
    `misc.py` silently dropped every pre-existing uncategorized object while
    the manifest kept tracking them, so the very next `hassle plan` proposed
    a DELETE for each one against live HA).

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
    one on disk -- the owner-smoke-test clobber, 101 adopted, 3 persisted;
    ``decompile_bundle`` natively emits multi-object modules, so batching is
    also the natural codegen shape). Source-only (no write) so
    `apply_pull_with_decompiler` can self-check every destination together
    before any of them is written (module docstring, coordinator task 4).

    ``snapshot`` (MILESTONES M18): threaded straight through to
    ``decompile_bundle`` -- a whole-file ADOPT batch can safely gain the new
    ``from hassle.services import <domains>`` header line (unlike `_refresh`'s
    single-object splice, a fresh whole-file write has no existing content to
    merge into)."""
    path = _entry_path(entries[0])
    objs = {e.object_key: _parsed(e.object_key, e.remote) for e in entries if e.remote is not None}
    return path, decompile_bundle(objs, script_refs=script_refs, snapshot=snapshot)


def _insert_category_global(source: str, category_name: str) -> str:
    """Insert ``CATEGORY = "<category_name>"`` right after ``source``'s
    import header (MILESTONES M12: pull emits the global when it CREATES a
    brand-new category file). Only ever called for a fresh ADOPT-batch
    destination that doesn't exist on disk yet -- an existing file's
    `CATEGORY` line is left alone entirely by the splicer (`hassle.decompiler.
    splice`'s `splice_object`/`remove_object` only ever touch the ONE
    statement matching a given object key; a plain `CATEGORY = "..."`
    assignment is never recognized as an object statement at all, so REFRESH/
    DROP simply never look at it, MILESTONES M12 test 4).

    Implemented with LibCST (already a decompiler-layer dependency) rather
    than string surgery, so the inserted statement is always syntactically
    well-formed regardless of what ``source`` looks like; a `ruff format`
    pass afterward keeps spacing byte-stable and consistent with
    `decompile_bundle`'s own formatting (R8: deterministic output).
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
    # Shared resolver (field failure #2, 2026-07-06): a bare "ruff" here
    # crashed standalone tool installs where the binary lives in the venv's
    # bin dir, not on PATH -- exactly the bug codegen._format_with_ruff had.
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


def apply_pull_with_decompiler(
    plan: Plan,
    source_writer: SourceWriter,
    *,
    category_display_names: dict[str, str] | None = None,
    snapshot: RegistrySnapshot | None = None,
) -> PullResult:
    """Same action dispatch as `hassle.sync.pull.apply_pull`, but real
    decompiled DSL content for `refresh`/`adopt` instead of the M5 placeholder.

    ``category_display_names`` (MILESTONES M12, additive): bundle-relative
    destination path -> the HA category's real display name (`hassle_cli.
    bundle_ops`/`cli.py`'s pull command builds this from the registry
    snapshot -- the same real name `bundle_ops._category_source_path`
    already slugifies for placement, never thrown away here). Only ever
    consulted for an ADOPT batch whose destination file does NOT already
    exist on disk -- i.e. pull is CREATING that category file for the first
    time (MILESTONES M12: "only when pull CREATES a new category file").
    Adopting a further object into an ALREADY-EXISTING file (category file
    or the shared `misc.py`) never re-emits or duplicates the global: the
    batch is MERGED into the existing content
    (:func:`_merge_adopt_batch_into_existing` -- append the decompiled
    objects, merge missing header imports, touch nothing else), so the
    file's existing `CATEGORY` line, objects, and hand-written comments all
    survive (I6; the BrandtCamp field failure, 2026-07-13, where this used
    to be a whole-file overwrite that dropped every pre-existing object).

    ``snapshot`` (MILESTONES M18): the same registry snapshot `cli.py`'s pull
    command already refreshes every pull -- threaded through to every
    `decompile_bundle` call this function makes, so a plain service-call
    action decompiles to the typed namespace form when the snapshot confirms
    the service exists (falls back to `service(...)` when `None`, unchanged
    pre-M18 behavior).
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
    # together (module docstring, coordinator task 4), THEN write -- so a
    # decompiler coordination bug is caught before any adopted file lands on
    # disk, with cross-file imports between two objects both being adopted
    # in this same pull resolving correctly (not checked one file at a time).
    batch_sources: dict[Path, str] = {}
    all_object_keys: list[str] = []
    original_configs: dict[str, dict[str, Any]] = {}
    for path, entries in adopts_by_path.items():
        batch_path, source = _adopt_batch_source(entries, script_refs, snapshot=snapshot)
        assert batch_path == path
        # MILESTONES M12: emit CATEGORY only for a file that doesn't exist
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
        # adopts into it) is MERGED into, never overwritten -- the whole-file
        # write here used to silently drop every pre-existing object in the
        # file while the manifest kept tracking them, so the next `hassle
        # plan` proposed a DELETE for each one (I6; the BrandtCamp field
        # failure, 2026-07-13). The self-check above already validated the
        # decompiled batch standalone; the merged file is covered by the
        # CLI's post-write whole-bundle backstop (`hassle_cli.cli.pull`),
        # which sees it exactly as the next compile will.
        if path.exists():
            source = _merge_adopt_batch_into_existing(path.read_text(encoding="utf-8"), source)
        source_writer.write_whole_file(path, source)

    for path, blocks in conflict_blocks_by_path.items():
        source_writer.write_whole_file(path, "\n".join(blocks))
    return PullResult(conflicts=conflicts)
