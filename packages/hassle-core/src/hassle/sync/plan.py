"""The plan engine — `compute_plan` — DESIGN §8.2 (the test spec).

For each object key, compares **base** (the manifest's `compiled_hash`),
**local** (freshly compiled, passed in by the caller), and **remote** (live
Backend data, passed in by the caller) via canonical hash equality
(`hassle.ir.canonical.sha256_hash`, per DESIGN §8.2: "remote (canonical-hashed)").
The output is one `PlanEntry` per object key, covering every row of the table
below verbatim:

| base vs remote       | base vs local | Plan action                                       |
|-----------------------|---------------|-----------------------------------------------------|
| same                  | same          | noop                                                 |
| same                  | different     | update                                               |
| same                  | local deleted | delete                                               |
| different (UI edit)   | same          | refresh                                              |
| different             | different     | conflict (both_edited)                               |
| different             | local deleted | conflict (deleted_locally_edited_remotely)            |
| remote deleted        | same          | drop                                                 |
| remote deleted        | different     | conflict (edited_locally_deleted_remotely)            |
| (new local id)        | —             | create (id-collision with new remote -> conflict)     |
| (new remote id)       | —             | adopt                                                 |

`compute_plan` is pure: it never touches a `Backend` or the filesystem; the
caller (M7's CLI, or a test) supplies local/remote as already-materialized
dicts. `manifest.lock` only stores the base *hash* (DESIGN §8.1), not the full
base config body, so `compute_plan` accepts an optional `base_objects` map
(object_key -> config) purely to populate `Conflict.base` for 3-way-diff
rendering (M7); the plan *decision* itself only ever depends on hash
comparisons, never on `base_objects`' content.
"""

from __future__ import annotations

from typing import Any

from hassle.ir.canonical import sha256_hash
from hassle.sync.models import Conflict, ConflictKind, Manifest, Plan, PlanAction, PlanEntry

# object_key -> (kind, config)
ObjectMap = dict[str, tuple[str, dict[str, Any]]]
BaseObjectMap = dict[str, dict[str, Any]]


def compute_plan(
    *,
    manifest: Manifest,
    local_objects: ObjectMap,
    remote_objects: ObjectMap,
    base_objects: BaseObjectMap | None = None,
) -> Plan:
    """Compute the three-way sync plan (DESIGN §8.2)."""
    base_objects = base_objects or {}
    all_keys = set(manifest.objects) | set(local_objects) | set(remote_objects)
    entries = [
        _plan_one(key, manifest, local_objects, remote_objects, base_objects)
        for key in sorted(all_keys)
    ]
    return Plan(entries=entries)


def _plan_one(
    object_key: str,
    manifest: Manifest,
    local_objects: ObjectMap,
    remote_objects: ObjectMap,
    base_objects: BaseObjectMap,
) -> PlanEntry:
    manifest_entry = manifest.objects.get(object_key)
    base_hash = manifest_entry.compiled_hash if manifest_entry is not None else None
    base_config = base_objects.get(object_key)

    local_kind, local_config = local_objects.get(object_key, (None, None))
    remote_kind, remote_config = remote_objects.get(object_key, (None, None))
    kind = local_kind or remote_kind or "unknown"

    local_hash = None if local_config is None else sha256_hash(local_config)
    remote_hash = None if remote_config is None else sha256_hash(remote_config)

    if base_hash is None:
        return _plan_no_base(object_key, kind, local_config, remote_config, remote_hash)

    base_vs_remote_same = base_hash == remote_hash
    base_vs_local_same = base_hash == local_hash

    def conflict(kind_: ConflictKind) -> Conflict:
        return Conflict(
            object_key=object_key,
            kind=kind_,
            base=base_config,
            local=local_config,
            remote=remote_config,
        )

    if remote_config is None:
        # remote deleted (base_hash != None == remote_hash's None-ness differs
        # from base only when base itself wasn't already "no remote" -- since
        # base_hash came from the manifest, an existing manifest entry always
        # implies the object previously existed remotely, so remote_config is
        # None here means "remote deleted since base").
        if local_config is None:
            # Both sides gone: nothing left to lose either way.
            return PlanEntry(object_key=object_key, kind=kind, action=PlanAction.DROP)
        if base_vs_local_same:
            return PlanEntry(object_key=object_key, kind=kind, action=PlanAction.DROP)
        return PlanEntry(
            object_key=object_key,
            kind=kind,
            action=PlanAction.CONFLICT,
            local=local_config,
            remote=None,
            conflict=conflict(ConflictKind.EDITED_LOCALLY_DELETED_REMOTELY),
        )

    if local_config is None:
        # local deleted, remote still present
        if base_vs_remote_same:
            return PlanEntry(
                object_key=object_key, kind=kind, action=PlanAction.DELETE, remote=remote_config
            )
        return PlanEntry(
            object_key=object_key,
            kind=kind,
            action=PlanAction.CONFLICT,
            local=None,
            remote=remote_config,
            remote_hash_at_plan=remote_hash,
            conflict=conflict(ConflictKind.DELETED_LOCALLY_EDITED_REMOTELY),
        )

    # Both sides present.
    if base_vs_remote_same and base_vs_local_same:
        action = PlanAction.NOOP
    elif base_vs_remote_same:
        action = PlanAction.UPDATE
    elif base_vs_local_same:
        action = PlanAction.REFRESH
    else:
        action = PlanAction.CONFLICT

    if action is PlanAction.CONFLICT:
        return PlanEntry(
            object_key=object_key,
            kind=kind,
            action=action,
            local=local_config,
            remote=remote_config,
            remote_hash_at_plan=remote_hash,
            conflict=conflict(ConflictKind.BOTH_EDITED),
        )
    return PlanEntry(
        object_key=object_key,
        kind=kind,
        action=action,
        local=local_config,
        remote=remote_config,
        remote_hash_at_plan=remote_hash,
    )


def _plan_no_base(
    object_key: str,
    kind: str,
    local_config: dict[str, Any] | None,
    remote_config: dict[str, Any] | None,
    remote_hash: str | None,
) -> PlanEntry:
    if local_config is not None and remote_config is not None:
        # id-collision: a new local id and a new remote object share a key.
        conflict = Conflict(
            object_key=object_key,
            kind=ConflictKind.BOTH_EDITED,
            base=None,
            local=local_config,
            remote=remote_config,
        )
        return PlanEntry(
            object_key=object_key,
            kind=kind,
            action=PlanAction.CONFLICT,
            local=local_config,
            remote=remote_config,
            remote_hash_at_plan=remote_hash,
            conflict=conflict,
        )
    if local_config is not None:
        return PlanEntry(
            object_key=object_key, kind=kind, action=PlanAction.CREATE, local=local_config
        )
    if remote_config is not None:
        return PlanEntry(
            object_key=object_key,
            kind=kind,
            action=PlanAction.ADOPT,
            remote=remote_config,
            remote_hash_at_plan=remote_hash,
        )
    # Neither side has it and there's no manifest entry: nothing to do. This
    # only happens if a caller passes a stray key with no data on any side.
    return PlanEntry(object_key=object_key, kind=kind, action=PlanAction.NOOP)
