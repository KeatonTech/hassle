"""`hassle.toml`'s `ignore` globs (DESIGN §8.2/§6 amendment, owner decision,
`ux/pull-organization`): a list of `fnmatch` patterns matched against object
keys (e.g. `"input_boolean:material_you_*"`). This REVISES §8.2's "first-ever
pull adopts everything; nothing is ever unmanaged" -- ignored keys are the one
deliberate exception.

Filtering happens **before** `hassle.sync.plan.compute_plan` ever runs (the CLI
calls `apply_ignore_globs` on the freshly-compiled local objects and the
freshly-fetched remote objects, then feeds the *filtered* maps to
`compute_plan`) -- the plan engine itself (F2, table-driven, MILESTONES M5)
needs no change and stays exactly the shape the M5 test suite pins.

Semantics:
- A key matching an ignore glob is dropped from BOTH `local_objects` and
  `remote_objects` before planning -- so it can never become `adopt`,
  `refresh`, `update`, or (the safety-critical case) `delete`: an object that
  exists remotely but is absent locally would otherwise plan as `delete`;
  filtering it out first means `compute_plan` never even sees that key, so a
  push can never touch it.
- If the object was ALSO declared locally (the user wrote DSL for something
  they're also ignoring -- almost certainly a mistake, e.g. they meant to
  ignore a *different* key), a `declared-but-ignored` warning `Finding` is
  emitted so `hassle pull`/`validate` can surface it.
"""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Any

from hassle.registry.finding import Finding
from hassle.sync.models import Manifest
from hassle.sync.plan import ObjectMap


@dataclass(frozen=True)
class IgnoreFilterResult:
    local_objects: ObjectMap
    remote_objects: ObjectMap
    findings: list[Finding]


def _matches_any(object_key: str, globs: list[str]) -> bool:
    return any(fnmatch(object_key, glob) for glob in globs)


def apply_ignore_globs(
    *,
    local_objects: ObjectMap,
    remote_objects: ObjectMap,
    ignore_globs: list[str],
) -> IgnoreFilterResult:
    """Filter ignored object keys out of both maps before `compute_plan` runs.

    Returns the filtered maps plus any `declared-but-ignored` warnings for
    keys that were present in `local_objects` (i.e. the user wrote DSL for
    something their own `ignore` list also matches)."""
    if not ignore_globs:
        return IgnoreFilterResult(local_objects, remote_objects, [])

    findings: list[Finding] = []
    filtered_local: ObjectMap = {}
    for key, value in local_objects.items():
        if _matches_any(key, ignore_globs):
            findings.append(
                Finding(
                    code="declared-but-ignored",
                    severity="warning",
                    file=None,
                    line=None,
                    message=(
                        f"`{key}` is declared locally but also matches an `ignore` "
                        f"glob in hassle.toml, so it will never be pushed, adopted, "
                        f"or refreshed."
                    ),
                    fix=(
                        "This is usually a mistake -- either remove the matching "
                        "`ignore` glob from hassle.toml if you DO want this object "
                        "managed, or delete/move the local declaration if you meant "
                        "to ignore it."
                    ),
                )
            )
            continue
        filtered_local[key] = value

    filtered_remote: ObjectMap = {
        key: value for key, value in remote_objects.items() if not _matches_any(key, ignore_globs)
    }

    return IgnoreFilterResult(filtered_local, filtered_remote, findings)


@dataclass(frozen=True)
class ManifestMigrationResult:
    manifest: Manifest
    dropped_keys: list[str]


def migrate_manifest_for_ignores(
    manifest: Manifest, *, ignore_globs: list[str]
) -> ManifestMigrationResult:
    """Drop manifest entries whose key newly matches an `ignore` glob.

    A glob added *after* a prior sync leaves stale `manifest.lock` entries for
    objects that must now be treated as unmanaged; those entries are removed
    (never touching HA -- this only edits the local manifest bookkeeping) and
    the caller prints a one-time notice per dropped key."""
    if not ignore_globs:
        return ManifestMigrationResult(manifest, [])

    dropped: list[str] = []
    kept: dict[str, Any] = {}
    for key, entry in manifest.objects.items():
        if _matches_any(key, ignore_globs):
            dropped.append(key)
        else:
            kept[key] = entry
    if not dropped:
        return ManifestMigrationResult(manifest, [])

    new_manifest = manifest.model_copy(update={"objects": kept})
    return ManifestMigrationResult(new_manifest, dropped)
