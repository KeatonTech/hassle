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

    Directly at the bundle root, one file per object
    (``<identity>.py``) -- **not** nested under an
    ``automations/``/``scripts/``/``helpers/`` subdirectory as DESIGN §6's
    bundle-format tree shows. `hassle.compiler.bundle.compile_bundle` only
    globs top-level ``*.py`` files in the directory it's pointed at; a file
    written into a subdirectory is invisible to the next compile, silently
    "losing" the object on the very next pull/plan (found while building
    this command -- docs/ha-api-notes.md §17.9 records the DESIGN/reality
    mismatch this works around).
    """
    _kind, _, identity = object_key.partition(":")
    return f"{identity}.py"


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
