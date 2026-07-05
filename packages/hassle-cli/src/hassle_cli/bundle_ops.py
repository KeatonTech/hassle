"""Compile a bundle directory into the `hassle.sync.plan.ObjectMap` shape the
sync engine (`compute_plan`/`apply_plan`) expects: `object_key -> (kind, config)`.

Also resolves each object's `source_path` (bundle-relative) from its
declaration-site span (`CompileResult.decl_span_for`), for `PlanEntry.source_path`
(routes the pull engine's `SourceWriter` calls, docs/backend.md).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hassle.compiler.bundle import CompileResult, compile_bundle
from hassle.ir.keys import HELPER_DOMAINS
from hassle.sync.plan import ObjectMap


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


def default_source_path(object_key: str) -> str:
    """Fallback path for a brand-new (adopted) object with no existing file.

    DESIGN §7.3's placement default: "one file per HA category/label if set,
    else ``automations/misc.py``" -- one ``misc.py`` per kind's tree
    subdirectory (``automations/``, ``scripts/``, ``helpers/``), matching
    what `hassle init` scaffolds and what the M7.1 loader (which now recurses,
    docs/ha-api-notes.md §17.9 RESOLVED) actually imports. After this first
    placement the object stays wherever the user moves it (tracked by the
    manifest); this is only the *initial* landing spot for an object nobody
    has ever pulled before.
    """
    kind, _, _identity = object_key.partition(":")
    if kind == "automation":
        return "automations/misc.py"
    if kind == "script":
        return "scripts/misc.py"
    if kind in HELPER_DOMAINS:
        return "helpers/misc.py"
    return f"{kind}s/misc.py"  # pragma: no cover - defensive, all OBJECT_KINDS covered above


def build_source_paths(
    bundle_root: Path, result: CompileResult, object_keys: list[str]
) -> dict[str, str]:
    paths: dict[str, str] = {}
    for key in object_keys:
        found = source_path_for(bundle_root, result, key)
        paths[key] = found if found is not None else default_source_path(key)
    return paths


def remote_objects_from_backend(backend: Any, kinds: list[str]) -> ObjectMap:
    from hassle.ir.keys import object_key as make_object_key

    objects: ObjectMap = {}
    for kind in kinds:
        for identity, config in backend.list_remote(kind).items():
            objects[make_object_key(kind, identity)] = (kind, config)
    return objects
