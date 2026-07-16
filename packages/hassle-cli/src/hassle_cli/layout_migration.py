"""MILESTONES M15 work item B -- one-time migration of an old-layout bundle
(the RETIRED per-kind-tree shape: `automations/<slug>.py` / `scripts/<slug>.py`
/ `helpers/<slug>.py`) into the new category-first, root-level layout.

**Trigger.** `hassle pull` detects an old-layout bundle by the presence of any
`.py` file under a top-level `automations/`, `scripts/`, or `helpers/`
directory (the three RETIRED trees -- DESIGN §6/§7.3). A bundle that never
had those directories, or has them but empty, needs no migration at all.

**What migration does, per MANAGED object currently declared under one of
those trees:**

1. Compute its NEW placement (`hassle_cli.bundle_ops.default_source_path` /
   the object's own existing declaration if it's not being newly adopted --
   in practice, for migration, every such object already has a source file,
   so its new destination is `bundle_ops`'s registry-aware category
   placement, falling back to the shared root `misc.py`).
2. If the new destination differs from the old one: **splice the object OUT**
   of its old file (`hassle.decompiler.splice.remove_object`, the exact same
   "remove one top-level statement" primitive `SplicingSourceWriter.
   delete_object` already uses for DROP) and **regenerate it** at the new
   destination (batched with every other object landing in that same new
   file, exactly like a fresh ADOPT batch -- `hassle.sync.pull_apply.
   _adopt_batch_source`'s shape, reused here via `decompile_bundle`).
3. **Old files are deleted ONLY when nothing but imports would remain**
   (I6 -- the exact same rule `remove_object`/`SplicingSourceWriter.
   delete_object` already apply to an ordinary DROP: a user's own comment
   attached to nothing, or bare imports, don't count as "content" worth
   keeping a file around for; a real top-level statement -- a custom `def`,
   a constant assignment, anything -- does, and the file survives with just
   the migrated object's statement removed).
4. **Every move is reported** (`MigrationReport.moves`, one entry per
   object), and every file actually deleted is reported too
   (`MigrationReport.deleted_files`) -- `hassle pull` prints both.
5. The manifest's `source` field is updated to the new path as part of the
   ordinary pull-side manifest advance (`hassle_cli.cli.pull` already does
   this for every REFRESH/ADOPT entry via `source_paths`) -- migration itself
   never touches HA or the manifest directly; it only rewrites working-tree
   files BEFORE compilation, so the normal compile -> plan -> pull-apply
   pipeline picks up each object at its new location on this same run.

**Why the plan stays a NOOP after migration**: `compute_plan` (DESIGN §8.2)
diffs purely on each object's compiled-JSON hash, never on `source_path` --
migration only moves DSL source between files (byte-identical compiled
output), so no object's hash changes and no CREATE/UPDATE/DELETE is ever
proposed because of a migration alone.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from hassle.compiler.bundle import CompileResult
from hassle.decompiler.codegen import decompile_bundle
from hassle.decompiler.splice import find_object_statement_name, remove_object
from hassle.ir.keys import OBJECT_KINDS
from hassle.registry.snapshot import RegistrySnapshot

_RETIRED_TREES: tuple[str, ...] = ("automations", "scripts", "helpers")


def _top_level_category_global(source: str) -> str | None:
    """The string value of a top-level ``CATEGORY = "..."`` assignment in
    ``source``, or ``None`` if there is none (or its value isn't a plain
    string literal). Polish-batch item 4(b): used only to flag an ORPHANED
    global left behind in a kept old-layout file after migration -- the file
    is no longer category-shaped (`hassle.ir.keys.category_shaped_stem`
    rejects every nested path, including the retired per-kind trees), so this
    global is now inert bundle-side metadata, not a re-parse of a live
    category capture (`hassle.compiler.bundle`'s own ``_category_global_span``
    is the load-bearing one for an ACTUAL category-shaped file; this is a
    diagnostic-only lookup on plain source text, best-effort like that
    function's own `ast`-parse approach)."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):  # pragma: no cover - defensive
        return None
    for stmt in tree.body:
        if (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
            and stmt.targets[0].id == "CATEGORY"
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str)
        ):
            return stmt.value.value
    return None


@dataclass(frozen=True)
class OrphanedCategoryGlobal:
    """A kept old-layout file's leftover `CATEGORY = "..."` global (polish-
    batch item 4(b)): the migrated object(s) that used to make this path
    category-shaped (under the M12-era per-kind-tree rule) have moved out,
    and M15's `category_shaped_stem` never recognizes a nested path as
    category-shaped at all -- so this global is now dead bundle-side
    metadata. Reported, never auto-removed (surgical splice territory the
    migration pass doesn't attempt); the user cleans it up by hand."""

    path: str
    category: str


def bundle_has_old_layout(bundle_root: Path) -> bool:
    """True if `bundle_root` has any `.py` file under one of the RETIRED
    per-kind trees (`automations/`, `scripts/`, `helpers/`) -- the signal
    `hassle pull` uses to decide whether migration is needed at all. An
    empty (or absent) tree needs no migration; a bundle that has already
    been migrated (or was `init`ed fresh under the new layout) never has
    these directories populated with `.py` files."""
    for tree in _RETIRED_TREES:
        tree_dir = bundle_root / tree
        if not tree_dir.is_dir():
            continue
        if any(p.suffix == ".py" for p in tree_dir.rglob("*.py")):
            return True
    return False


@dataclass(frozen=True)
class MigrationMove:
    """One object's move from its old-layout file to its new one."""

    object_key: str
    old_path: str
    new_path: str


@dataclass
class MigrationReport:
    moves: list[MigrationMove] = field(default_factory=list)
    deleted_files: list[str] = field(default_factory=list)
    # Polish-batch item 4(b): kept old-tree files (I6 -- not deleted, because
    # something besides the migrated object(s) remains) whose only remaining
    # "content" is an orphaned `CATEGORY = "..."` global from the M12 era.
    # Note (also polish-batch item 4(b)): any now-unused import left in a kept
    # old file is deliberately NOT reported or auto-removed here -- migration
    # only ever splices OUT the migrated object's own statement, never
    # rewrites the rest of the file, so a leftover `from hassle import
    # automation` with nothing left to use it is left as-is for the user to
    # clean up (same "never touch what migration didn't move" principle as
    # the orphaned CATEGORY global itself).
    orphaned_category_globals: list[OrphanedCategoryGlobal] = field(default_factory=list)

    @property
    def migrated(self) -> bool:
        return bool(self.moves)


def _is_old_layout_path(source_path: str | None) -> bool:
    if source_path is None:
        return False
    parts = source_path.split("/")
    return len(parts) >= 2 and parts[0] in _RETIRED_TREES


def migrate_old_layout(
    bundle_root: Path,
    compile_result: CompileResult,
    *,
    registry: RegistrySnapshot | None,
    new_source_path_for: dict[str, str],
) -> MigrationReport:
    """Move every compiled object whose CURRENT declaration lives under a
    RETIRED per-kind tree to its NEW (root-level, category-first) file,
    splicing it out of the old file and regenerating it at the new
    destination -- old files are deleted only when no user content remains
    (I6). Mutates the working tree; returns a report of every move/deletion
    for `hassle pull` to print.

    ``new_source_path_for`` is `object_key -> new bundle-relative path`,
    precomputed by the caller (`hassle_cli.bundle_ops.build_source_paths`,
    the SAME placement every other pull path already uses -- migration does
    not invent a second placement policy). ``registry`` is accepted for
    interface symmetry with that same caller-side placement call (and so a
    future revision of this function can consult it directly without an API
    change) but is not read here -- the placement decision it would inform is
    already baked into ``new_source_path_for`` by the time this function
    runs.
    """
    del registry
    report = MigrationReport()

    # Group every to-be-migrated object by its OLD file (so a shared old
    # file's siblings are spliced out one at a time, in the same pass) and
    # by its NEW file (so objects landing on the same new destination are
    # regenerated together in one multi-object module, exactly like a fresh
    # ADOPT batch -- never last-writer-wins).
    by_old_path: dict[str, list[str]] = {}
    by_new_path: dict[str, list[str]] = {}
    for object_key in compile_result.objects:
        kind = object_key.partition(":")[0]
        if kind not in OBJECT_KINDS:
            continue  # defensive
        old_path = None
        span = compile_result.decl_span_for(object_key)
        if span is not None:
            try:
                old_path = str(Path(span.file).resolve().relative_to(bundle_root.resolve()))
            except ValueError:
                old_path = span.file
        old_path_posix = Path(old_path).as_posix() if old_path else None
        if not _is_old_layout_path(old_path_posix):
            continue
        assert old_path_posix is not None
        new_path = new_source_path_for.get(object_key)
        if new_path is None or new_path == old_path_posix:
            continue  # already at its new home (shouldn't normally happen pre-migration)
        by_old_path.setdefault(old_path_posix, []).append(object_key)
        by_new_path.setdefault(new_path, []).append(object_key)
        report.moves.append(
            MigrationMove(object_key=object_key, old_path=old_path_posix, new_path=new_path)
        )

    if not report.moves:
        return report

    # 1. Splice every migrated object OUT of its old file (delete the file
    #    entirely when nothing but imports would remain -- I6).
    for old_path_posix, object_keys in sorted(by_old_path.items()):
        old_file = bundle_root / old_path_posix
        if not old_file.is_file():
            continue
        source = old_file.read_text(encoding="utf-8")
        for object_key in object_keys:
            target_name = find_object_statement_name(source, object_key)
            if target_name is None:
                continue  # already gone from this file somehow -- nothing to splice
            remaining = remove_object(source, object_key=object_key)
            if remaining is None:
                source = None  # type: ignore[assignment]
                break
            source = remaining
        if source is None:
            old_file.unlink()
            report.deleted_files.append(old_path_posix)
        else:
            old_file.write_text(source, encoding="utf-8")
            # Polish-batch item 4(b): the file was kept (I6 -- something
            # besides the migrated object remains) -- flag it if that
            # "something" is (at least) an orphaned CATEGORY global left
            # over from the M12-era per-kind-tree category shape, now inert
            # under M15's root-level-only `category_shaped_stem`.
            category_value = _top_level_category_global(source)
            if category_value is not None:
                report.orphaned_category_globals.append(
                    OrphanedCategoryGlobal(path=old_path_posix, category=category_value)
                )

    # 2. Regenerate every migrated object at its NEW destination, batched by
    #    destination file (mixed-kind files land here naturally -- the same
    #    kind-agnostic `decompile_bundle` every other pull path already uses).
    for new_path, object_keys in sorted(by_new_path.items()):
        dest = bundle_root / new_path
        objs = {key: compile_result.objects[key] for key in object_keys}
        new_source = decompile_bundle(objs)
        if dest.is_file():
            # Splicing into an existing (already-migrated, or hand-authored)
            # file: append via the same "no matching statement" fallback
            # `SplicingSourceWriter.splice_object` uses for a stale-manifest
            # refresh, so any existing content in `dest` survives untouched.
            from hassle.decompiler.splice import merge_missing_imports, split_module_source

            import_sources, object_sources = split_module_source(new_source)
            existing = dest.read_text(encoding="utf-8")
            appended = (
                existing.rstrip("\n") + "\n\n\n" + "\n\n".join(object_sources).strip("\n") + "\n"
            )
            dest.write_text(merge_missing_imports(appended, import_sources), encoding="utf-8")
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(new_source, encoding="utf-8")

    report.moves.sort(key=lambda m: m.object_key)
    return report
