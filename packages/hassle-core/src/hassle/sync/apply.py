"""The apply engine — `apply_plan` — DESIGN §8.2 (push-side actions).

Executes the push-side actions of a `Plan` (`create`/`update`/`delete`)
against a `Backend`, in dependency order **helpers -> scripts -> automations**
(DESIGN §8.2, docs/ha-api-notes.md §11), with two safety mechanisms:

- **Re-verification.** Before writing each object, its live remote hash is
  re-fetched and compared against `PlanEntry.remote_hash_at_plan` (the hash
  captured when the plan was computed). Any drift aborts the whole apply
  before that object (or anything after it) is written
  (`test_apply_reverifies_hashes`).
- **Transactional-ish rollback.** Every to-be-touched object's current remote
  state is snapshotted before any writes. If a step fails partway through,
  every previously-applied object in this run is restored from its snapshot
  via `Backend` calls, so the backend's final state == its initial state
  (`test_apply_order_and_rollback`).

`manifest.lock` is only rewritten (returned via `ApplyResult.manifest`) when
every entry succeeds; on any failure the caller keeps its old manifest
(`test_manifest_updates_only_on_success`). `synced_at` is never computed here
(R8) — it's supplied by the caller, defaulting to the incoming manifest's own
value if the caller doesn't advance it explicitly.
"""

from __future__ import annotations

from hassle.backend.protocol import Backend
from hassle.ir.canonical import sha256_hash
from hassle.sync.models import (
    ApplyOutcome,
    ApplyResult,
    Manifest,
    ManifestEntry,
    Plan,
    PlanAction,
    PlanEntry,
)

# Push-side apply order (DESIGN §8.2 / docs/ha-api-notes.md §11): helper
# domains first (any order among themselves), then scripts, then automations
# (automations may reference scripts/helpers, so those must exist first).
_KIND_ORDER = (
    "input_boolean",
    "input_number",
    "input_select",
    "input_text",
    "input_datetime",
    "input_button",
    "counter",
    "timer",
    "schedule",
    "script",
    "automation",
)


def _kind_sort_key(kind: str) -> int:
    try:
        return _KIND_ORDER.index(kind)
    except ValueError:
        return len(_KIND_ORDER)


_PUSH_ACTIONS = (PlanAction.CREATE, PlanAction.UPDATE, PlanAction.DELETE)


def apply_plan(
    plan: Plan, backend: Backend, manifest: Manifest, *, synced_at: str | None = None
) -> ApplyResult:
    """Apply the push-side actions of ``plan`` against ``backend``."""
    push_entries = [entry for entry in plan.entries if entry.action in _PUSH_ACTIONS]
    push_entries.sort(key=lambda entry: _kind_sort_key(entry.kind))

    outcomes: dict[str, ApplyOutcome] = {}
    # (kind, identity) -> snapshot of the pre-apply remote config (None if the
    # object didn't exist yet, e.g. a CREATE).
    snapshots: list[tuple[str, str, dict[str, object] | None]] = []
    applied: list[str] = []  # object_keys successfully applied, in apply order

    for entry in push_entries:
        identity = _identity_of(entry.object_key)

        if entry.action in (PlanAction.UPDATE, PlanAction.DELETE):
            remote_now = backend.list_remote(entry.kind).get(identity)
            remote_hash_now = None if remote_now is None else sha256_hash(remote_now)
            if remote_hash_now != entry.remote_hash_at_plan:
                # Drift since plan time: abort before writing this or anything
                # after it. Nothing beyond what's already applied is touched.
                outcomes[entry.object_key] = ApplyOutcome.ABORTED
                _mark_remaining_aborted(push_entries, entry, outcomes)
                _rollback(backend, snapshots)
                return ApplyResult(outcomes=outcomes, succeeded=False, manifest=None)
            snapshots.append((entry.kind, identity, remote_now))
        else:  # CREATE
            snapshots.append((entry.kind, identity, None))

        try:
            _apply_one(backend, entry, identity)
        except Exception:
            outcomes[entry.object_key] = ApplyOutcome.FAILED
            _mark_remaining_aborted(push_entries, entry, outcomes, skip_first=True)
            _rollback(backend, snapshots[:-1])
            for key in applied:
                outcomes[key] = ApplyOutcome.ROLLED_BACK
            return ApplyResult(outcomes=outcomes, succeeded=False, manifest=None)

        outcomes[entry.object_key] = ApplyOutcome.SUCCEEDED
        applied.append(entry.object_key)

    new_manifest = _advance_manifest(manifest, backend, push_entries, synced_at)
    return ApplyResult(outcomes=outcomes, succeeded=True, manifest=new_manifest)


def _identity_of(object_key: str) -> str:
    _, _, identity = object_key.partition(":")
    return identity


def _apply_one(backend: Backend, entry: PlanEntry, identity: str) -> None:
    if entry.action is PlanAction.CREATE:
        assert entry.local is not None
        backend.create(entry.kind, entry.local)
    elif entry.action is PlanAction.UPDATE:
        assert entry.local is not None
        backend.update(entry.kind, identity, entry.local)
    elif entry.action is PlanAction.DELETE:
        backend.delete(entry.kind, identity)


def _mark_remaining_aborted(
    push_entries: list[PlanEntry],
    failed_entry: PlanEntry,
    outcomes: dict[str, ApplyOutcome],
    skip_first: bool = False,
) -> None:
    started = False
    for entry in push_entries:
        if entry is failed_entry:
            started = True
            if skip_first:
                continue
        if started and entry.object_key not in outcomes:
            outcomes[entry.object_key] = ApplyOutcome.ABORTED


def _rollback(backend: Backend, snapshots: list[tuple[str, str, dict[str, object] | None]]) -> None:
    # Restore in reverse order of application.
    for kind, identity, previous in reversed(snapshots):
        if previous is None:
            # It didn't exist before (this was a CREATE) -> delete it back out.
            backend.delete(kind, identity)
        else:
            backend.update(kind, identity, previous)


def _advance_manifest(
    manifest: Manifest, backend: Backend, push_entries: list[PlanEntry], synced_at: str | None
) -> Manifest:
    new_objects = dict(manifest.objects)
    for entry in push_entries:
        identity = _identity_of(entry.object_key)
        if entry.action is PlanAction.DELETE:
            new_objects.pop(entry.object_key, None)
            continue
        current = backend.list_remote(entry.kind).get(identity)
        if current is None:
            continue
        existing = manifest.objects.get(entry.object_key)
        new_objects[entry.object_key] = ManifestEntry(
            source=existing.source if existing is not None else None,
            compiled_hash=sha256_hash(current),
            kind=existing.kind if existing is not None else "dsl",
        )
    return Manifest(
        synced_at=synced_at if synced_at is not None else manifest.synced_at,
        ha_version=manifest.ha_version,
        objects=new_objects,
    )
