"""Compile a bundle directory into the `hassle.sync.plan.ObjectMap` shape the
sync engine (`compute_plan`/`apply_plan`) expects: `object_key -> (kind, config)`.

Also resolves each object's `source_path` (bundle-relative) from its
declaration-site span (`CompileResult.decl_span_for`), for `PlanEntry.source_path`
(routes the pull engine's `SourceWriter` calls, docs/internals/backend-protocol.md).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from hassle.compiler.bundle import CompileResult, compile_bundle
from hassle.ir.keys import category_shaped_stem
from hassle.ir.keys import slugify as _slugify
from hassle.registry.snapshot import RegistrySnapshot
from hassle.sync.category_writeback import (
    _SCOPE_FOR_KIND,  # pyright: ignore[reportPrivateUsage]
)
from hassle.sync.plan import ObjectMap

if TYPE_CHECKING:
    from hassle.decompiler.codegen import ScriptRef


def compile_local_objects(bundle_root: Path) -> tuple[ObjectMap, CompileResult]:
    """Compile every DSL source under `bundle_root` and return the plan-ready
    object map alongside the raw `CompileResult` (for source-path/span lookups
    and for validation)."""
    result = compile_bundle(bundle_root)
    objects: ObjectMap = {}
    for key, obj in result.objects.items():
        objects[key] = (obj.kind(), obj.to_ha())
    return objects, result


def category_overrides_and_warnings(
    result: CompileResult,
) -> tuple[dict[str, str], list[str]]:
    """`hassle.sync.apply.apply_plan`'s `category_overrides` map
    (bundle-relative source path -> exact display name), built from every
    bundle file's `CATEGORY` global that actually slugifies to its own file
    stem -- alongside a list of warning strings for every file whose
    `CATEGORY` does NOT (the "write-back additionally ignores the global with
    a warning" half of this binding semantics rule; the compile-time
    Finding, `hassle.registry.validate`'s `category-slug-mismatch`, is the
    other half of that same rule, surfaced via `hassle validate`/`plan`
    instead of push's own warning stream).

    A mismatched file's `CATEGORY` is deliberately left OUT of the returned
    map (never passed through as an override) -- `apply_plan`'s fallback for
    an entry with no override entry is exactly `humanize_slug`'s guess,
    which is the correct "don't guess which side is right" behavior here.
    """
    overrides: dict[str, str] = {}
    warnings: list[str] = []
    for source_path, category in result.category_globals.items():
        stem = Path(source_path).stem
        if _slugify(category.value) == stem:
            overrides[source_path] = category.value
        else:
            warnings.append(
                f'hassle push: `CATEGORY = "{category.value}"` in `{source_path}` does not '
                f"slugify to this file's own name -- ignoring it (falling back to a "
                f"slug-derived category name if a new category has to be created). Fix: "
                f"rename the file or change `CATEGORY` so they agree (see `hassle validate`)."
            )
    return overrides, warnings


def source_path_for(bundle_root: Path, result: CompileResult, object_key: str) -> str | None:
    span = result.decl_span_for(object_key)
    if span is None:
        return None
    try:
        return str(Path(span.file).resolve().relative_to(bundle_root.resolve()))
    except ValueError:
        return span.file


def _category_source_path(object_key: str, registry: RegistrySnapshot) -> str | None:
    """DESIGN §7.3's placement default, the category-registry half
    (root-level, cross-kind layout, docs/internals/ha-api-notes.md §31.6): an object's
    entity-registry entry (matched by `unique_id ==
    identity`, the id<->unique_id anchor, docs/internals/ha-api-notes.md §2) may carry a
    UI category for its OWN scope (``"automation"``/``"script"`` for those two
    kinds, the shared ``"helpers"`` scope for all 13 helper kinds); if so,
    place it under root-level ``<slug(category name)>.py`` instead of the
    flat ``misc.py``.

    **Placement = category, derived from the object's OWN scope**: the
    entity-registry lookup filters by
    `kind` (the real HA domain, e.g. `input_boolean`), but the CATEGORY lookup
    itself uses `kind`'s category-registry scope (`_SCOPE_FOR_KIND` --
    `automation`/`script` for those two kinds, `"helpers"` for every helper
    kind) -- never the other way around. Same category NAME across scopes
    naturally lands at the same file (a slug is just a slug); a name that
    diverges across scopes for what used to be one shared file is a pull-time
    warning (`category_divergence_warnings`), never guessed here -- this
    function only ever answers for ONE object at a time.
    """
    kind, _, identity = object_key.partition(":")
    scope = _SCOPE_FOR_KIND.get(kind)
    if scope is None:
        return None
    entity = registry.entity_by_unique_id(kind, identity)
    if entity is None:
        return None
    category_name = registry.category_name_for_entity(scope, entity)
    if not category_name:
        return None
    return f"{_slugify(category_name)}.py"


def category_display_names_for_paths(
    object_keys: list[str], registry: RegistrySnapshot
) -> dict[str, str]:
    """Destination path -> that category's real HA display name (applies to
    every object kind), for every
    ``object_keys`` entry that has a UI-assigned category (the exact same
    `_category_source_path` anchor `default_source_path` already uses for
    placement -- this just also keeps the display NAME it would otherwise
    throw away, for `hassle pull` to emit as the new category file's
    `CATEGORY` global).

    Only ever consulted by `hassle.sync.pull_apply.apply_pull_with_decompiler`
    for an ADOPT batch whose destination file does not already exist --
    i.e. this dict may (harmlessly) also contain paths for objects landing
    in an ALREADY-EXISTING category file; the caller is what decides whether
    the destination is actually new.

    When two objects of DIFFERENT scopes land on the SAME
    slugified name here by construction (they only share a file because
    their own scope's category slugifies the same) -- so whichever is
    processed last simply confirms the same display name; no special
    dict-merge handling is needed.
    """
    names: dict[str, str] = {}
    for object_key in object_keys:
        kind, _, identity = object_key.partition(":")
        scope = _SCOPE_FOR_KIND.get(kind)
        if scope is None:
            continue
        entity = registry.entity_by_unique_id(kind, identity)
        if entity is None:
            continue
        category_name = registry.category_name_for_entity(scope, entity)
        if not category_name:
            continue
        path = f"{_slugify(category_name)}.py"
        names[path] = category_name
    return names


def default_source_path(object_key: str, *, registry: RegistrySnapshot | None = None) -> str:
    """Fallback path for a brand-new (adopted) object with no existing file.

    DESIGN §7.3, category-first layout: root-level mixed-kind files. When
    `registry` is supplied and the object has a UI-assigned category under
    its OWN scope's category-registry scope (`_category_source_path`), it
    lands under root-level ``<slug(category name)>.py`` -- the SAME file an
    automation/script/helper with a same-named category in any of the other
    two scopes would land in (placement is derived independently per object,
    from its own scope; it just so happens a shared slug means a shared
    file). Otherwise (no registry, or the object is uncategorized) it falls
    back to the single root-level ``misc.py`` -- one shared uncategorized
    file for every kind, replacing the old per-tree ``automations/misc.py``
    / ``scripts/misc.py`` / ``helpers/misc.py`` trio (retired shape). After
    this first placement the object stays wherever the user moves it
    (tracked by the manifest); this is only the *initial* landing spot for
    an object nobody has ever pulled before.
    """
    if registry is not None:
        categorized = _category_source_path(object_key, registry)
        if categorized is not None:
            return categorized

    return "misc.py"


def build_source_paths(
    bundle_root: Path,
    result: CompileResult,
    object_keys: list[str],
    *,
    registry: RegistrySnapshot | None = None,
) -> dict[str, str]:
    paths: dict[str, str] = {}
    for key in object_keys:
        found = source_path_for(bundle_root, result, key)
        paths[key] = found if found is not None else default_source_path(key, registry=registry)
    return paths


def category_divergence_warnings(
    previous_source_paths: dict[str, str | None],
    new_source_paths: dict[str, str],
) -> list[str]:
    """The divergence policy: if HA-side renames make the scopes' names
    diverge for what was one file, pull places each object by its OWN
    scope's category (files may split) and emits a divergence warning
    naming the scopes -- never guesses a winner.

    Placement itself (`_category_source_path`/`default_source_path`) already
    does the "place by own scope" half unconditionally -- it never needs to
    know about divergence at all, since it only ever resolves one object at a
    time. This function is the OTHER half: detecting that a split actually
    happened, by comparing every object's PREVIOUS placement (the manifest's
    recorded `source`, ``previous_source_paths``) against its freshly
    computed new placement (``new_source_paths``, this pull's
    `build_source_paths` output). Objects that used to share one destination
    file (by manifest record) but no longer do -- because their own scope's
    category name diverged from a sibling scope's -- produce ONE warning per
    old shared file, naming every DIFFERENT kind now involved (never which
    kind is "right"; both are just what their own scope says).

    A single-kind split (every formerly-shared occupant is still one kind, or
    they still all land on the same new path) is not a scope divergence --
    ordinary same-scope re-categorization already has its own (per-object,
    silent) handling; this warning is specifically for the CROSS-SCOPE case.

    Only warn when the OLD shared path was
    ITSELF category-derived (``category_shaped_stem(old_path) is not
    None``). A user who hand-grouped a mixed-kind file under a name that was
    never a category placement (``misc.py``, a nested `lib/`/`tests/`/`docs/`
    path, ...) and later has ONE of those objects gain a real HA category
    simply sees that object move to its own new placement -- there was never
    a shared category for anything to "diverge" from, so this is ordinary
    per-object re-categorization, not the cross-scope-rename situation this
    warning exists for.
    """
    old_groups: dict[str, set[str]] = {}
    for object_key, old_path in previous_source_paths.items():
        if old_path is None:
            continue
        old_groups.setdefault(old_path, set()).add(object_key)

    warnings: list[str] = []
    for old_path, member_keys in sorted(old_groups.items()):
        if len(member_keys) < 2:
            continue
        if category_shaped_stem(old_path) is None:
            continue  # never a category placement to begin with -- nothing diverged
        new_paths = {new_source_paths[k] for k in member_keys if k in new_source_paths}
        if len(new_paths) < 2:
            continue  # still all together (or none of them are in this pull)
        kinds_involved = sorted({k.partition(":")[0] for k in member_keys if k in new_source_paths})
        if len(kinds_involved) < 2:
            continue  # split, but not a cross-SCOPE divergence
        scopes_involved = sorted({_SCOPE_FOR_KIND.get(kind, kind) for kind in kinds_involved})
        if len(scopes_involved) < 2:
            continue  # e.g. every helper kind shares "helpers" -- not a real divergence
        # Never render a Python list/`[...]`-bracketed group directly into the
        # message: `hassle pull`'s CLI layer prints warnings through rich's
        # `Console.print`, which treats a bare `[...]` substring as markup
        # (a style tag) and SILENTLY SWALLOWS it -- an earlier version of
        # this message rendered `scopes_involved` and a `[{destinations}]`
        # bracketed list directly and the scope names/destination paths
        # vanished from the printed warning entirely (field failure caught
        # by `test_pull_category_divergence.py`). Comma-joined, unbracketed
        # text only, from here on.
        scopes_text = ", ".join(scopes_involved)
        destinations = ", ".join(sorted(new_paths))
        warnings.append(
            f"hassle pull: {old_path!r} used to be shared by scopes {scopes_text} -- "
            f"their category names have since diverged in HA's UI, so this pull splits it "
            f"across {destinations} (placing each object under its own scope's category, "
            "never guessing which side is right). Fix: rename the category consistently "
            "across HA's automation/script/helpers tables if you want them back in one file."
        )
    return warnings


def remote_objects_from_backend(backend: Any, kinds: list[str]) -> ObjectMap:
    from hassle.ir.keys import object_key as make_object_key

    objects: ObjectMap = {}
    for kind in kinds:
        for identity, config in backend.list_remote(kind).items():
            objects[make_object_key(kind, identity)] = (kind, config)
    return objects


def _module_path_for(source_path: str) -> str:
    """A bundle-relative ``.py`` file path -> the dotted module path an
    ``import`` statement would use (``"scripts/notify.py"`` ->
    ``"scripts.notify"``) -- the bundle loader imports every bundle file this
    way (recursive PEP 420 namespace packages, no ``__init__.py`` needed,
    docs/internals/ha-api-notes.md §17.9 RESOLVED), so this is just that same mapping
    run forward instead of backward."""
    posix = Path(source_path).as_posix()
    if posix.endswith(".py"):
        posix = posix[: -len(".py")]
    return posix.replace("/", ".")


def build_script_refs(
    scripts: dict[str, Any], source_paths: dict[str, str]
) -> dict[str, ScriptRef]:
    """Build the shared-script-calls cross-reference table
    (``{script_object_id: ScriptRef}``) for every MANAGED script in a pull
    batch, from the same ``source_paths`` placement (DESIGN §7.3) the pull
    loop already computes for every object.

    ``scripts`` maps each script's object key to its HA config body (the
    plan's ``remote`` value for that entry) -- used to derive the exact
    function name :func:`hassle.decompiler.codegen.script_function_name`
    would (alias-derived, not object_id-derived, DESIGN §7.3), the callee's
    declared field names, and its own outgoing ``script.<id>`` call graph
    (for cross-file cycle detection). Naming collisions are resolved
    independently per destination file (a fresh ``used_names`` tracker per
    module path), matching how each file is actually decompiled on its own in
    `hassle.sync.pull_apply` (one `decompile_bundle` call per destination).

    Every ``ScriptRef``
    also carries ``is_shared_script`` -- whether ``obj`` actually decompiles
    to ``@shared_script`` (:func:`hassle.decompiler.codegen.
    script_is_shared_script`) rather than falling back to plain ``@script``
    (DESIGN §7.3's fallback rule). A fallback script has NO call-site
    parameters at all, whatever its ``fields`` block's key names are --
    ``known_fields`` alone is not enough to gate the caller rewrite; the
    resolver checks ``is_shared_script`` first (see
    ``hassle.decompiler.codegen._build_resolver``'s docstring for the exact
    field failure this fixes).
    """
    from hassle.decompiler.codegen import (
        ScriptRef,
        called_script_ids,
        script_function_name,
        script_is_shared_script,
    )
    from hassle.ir.models import ScriptConfig, parse

    # Group by destination file so alias-collision suffixing matches exactly
    # what decompiling that one file for real would produce.
    by_path: dict[str, list[tuple[str, ScriptConfig]]] = {}
    for key, config in scripts.items():
        kind, _, identity = key.partition(":")
        if kind != "script":
            continue
        path = source_paths.get(key)
        if path is None:
            continue
        obj = parse(config, kind="script", key_hint=identity)
        assert isinstance(obj, ScriptConfig)
        by_path.setdefault(path, []).append((identity, obj))

    refs: dict[str, ScriptRef] = {}
    for path, entries in by_path.items():
        module = _module_path_for(path)
        used_names: dict[str, int] = {}
        for identity, obj in sorted(entries, key=lambda pair: pair[0]):
            fn_name = script_function_name(obj, used_names)
            fields = obj.to_ha().get("fields")
            known_fields = frozenset(fields) if isinstance(fields, dict) else frozenset()
            calls = frozenset(called_script_ids(obj.to_ha()))
            refs[identity] = ScriptRef(
                module=module,
                function_name=fn_name,
                known_fields=known_fields,
                is_shared_script=script_is_shared_script(obj),
                calls=calls,
            )
    return refs
