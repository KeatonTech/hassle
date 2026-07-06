"""Compile a bundle directory into the `hassle.sync.plan.ObjectMap` shape the
sync engine (`compute_plan`/`apply_plan`) expects: `object_key -> (kind, config)`.

Also resolves each object's `source_path` (bundle-relative) from its
declaration-site span (`CompileResult.decl_span_for`), for `PlanEntry.source_path`
(routes the pull engine's `SourceWriter` calls, docs/backend.md).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from hassle.compiler.bundle import CompileResult, compile_bundle
from hassle.ir.keys import HELPER_DOMAINS, TEMPLATE_DOMAINS
from hassle.ir.keys import slugify as _slugify
from hassle.registry.snapshot import RegistrySnapshot
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


def source_path_for(bundle_root: Path, result: CompileResult, object_key: str) -> str | None:
    span = result.decl_span_for(object_key)
    if span is None:
        return None
    try:
        return str(Path(span.file).resolve().relative_to(bundle_root.resolve()))
    except ValueError:
        return span.file


def _category_source_path(object_key: str, registry: RegistrySnapshot) -> str | None:
    """DESIGN §7.3's placement default, the category-registry half: an
    object's entity-registry entry (matched by `unique_id == identity`, the
    id<->unique_id anchor, docs/ha-api-notes.md §2) may carry a UI category
    for its scope (``"automation"``/``"script"`` -- the only two scopes HA's
    category registry covers); if so, place it under
    ``<tree>/<slug(category name)>.py`` instead of the flat ``misc.py``.
    Helpers have no category-registry scope, so this always returns None for
    them (they keep the plain domain-default fallback)."""
    kind, _, identity = object_key.partition(":")
    if kind not in ("automation", "script"):
        return None
    entity = registry.entity_by_unique_id(kind, identity)
    if entity is None:
        return None
    category_name = registry.category_name_for_entity(kind, entity)
    if not category_name:
        return None
    tree = "automations" if kind == "automation" else "scripts"
    return f"{tree}/{_slugify(category_name)}.py"


def default_source_path(object_key: str, *, registry: RegistrySnapshot | None = None) -> str:
    """Fallback path for a brand-new (adopted) object with no existing file.

    DESIGN §7.3's placement default: "one file per HA category/label if set,
    else ``automations/misc.py``". When `registry` is supplied and the object
    has a UI-assigned category (automations/scripts only), it lands under
    ``<tree>/<slug(category name)>.py``; otherwise (no registry, no category
    registry scope for this kind, or the object is uncategorized) it falls
    back to one ``misc.py`` per kind's tree subdirectory (``automations/``,
    ``scripts/``, ``helpers/``), matching what `hassle init` scaffolds and
    what the M7.1 loader (which now recurses, docs/ha-api-notes.md §17.9
    RESOLVED) actually imports. After this first placement the object stays
    wherever the user moves it (tracked by the manifest); this is only the
    *initial* landing spot for an object nobody has ever pulled before.

    M10: the four config-entry template-helper domains (``TEMPLATE_DOMAINS``)
    place under ``helpers/misc.py`` exactly like the nine storage-collection
    helper domains -- same category/misc placement rules (DESIGN §5.7/§7.3
    treat every helper domain the same way from the bundle-layout point of
    view; only the sync/apply mechanics differ, docs/backend.md).
    """
    if registry is not None:
        categorized = _category_source_path(object_key, registry)
        if categorized is not None:
            return categorized

    kind, _, _identity = object_key.partition(":")
    if kind == "automation":
        return "automations/misc.py"
    if kind == "script":
        return "scripts/misc.py"
    if kind in HELPER_DOMAINS or kind in TEMPLATE_DOMAINS:
        return "helpers/misc.py"
    return f"{kind}s/misc.py"  # pragma: no cover - defensive, all OBJECT_KINDS covered above


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
    ``"scripts.notify"``) -- the M7.1 loader imports every bundle file this
    way (recursive PEP 420 namespace packages, no ``__init__.py`` needed,
    docs/ha-api-notes.md §17.9 RESOLVED), so this is just that same mapping
    run forward instead of backward."""
    posix = Path(source_path).as_posix()
    if posix.endswith(".py"):
        posix = posix[: -len(".py")]
    return posix.replace("/", ".")


def build_script_refs(
    scripts: dict[str, Any], source_paths: dict[str, str]
) -> dict[str, ScriptRef]:
    """Build the ``ux/shared-script-calls`` cross-reference table
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
    `hassle_cli.pull_apply` (one `decompile_bundle` call per destination).

    **Field-failure fix (``ux/shared-script-calls-fix``):** every ``ScriptRef``
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
