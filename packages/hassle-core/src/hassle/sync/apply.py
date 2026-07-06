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

**M11: category write-back on CREATE.** Immediately after a CREATE succeeds
for an automation/script, `hassle.sync.category_writeback.
attempt_category_writeback` is given a chance to assign the HA UI category
implied by `PlanEntry.source_path` (DESIGN §7.3's placement, run in reverse).
This never affects apply's own success/rollback bookkeeping (I6: it's pure
metadata, and a failure here is surfaced as a warning in
`ApplyResult.category_warnings`, never an aborted/rolled-back object,
MILESTONES M11 test 3) and is never attempted for any action besides a
freshly-succeeded CREATE (MILESTONES M11 test 4).
"""

from __future__ import annotations

from hassle.backend.protocol import Backend
from hassle.ir.canonical import sha256_hash
from hassle.sync.category_writeback import attempt_category_writeback
from hassle.sync.models import (
    ApplyOutcome,
    ApplyResult,
    Manifest,
    ManifestEntry,
    Plan,
    PlanAction,
    PlanEntry,
)

# Push-side apply order (DESIGN §8.2 / docs/ha-api-notes.md §11): storage
# helper domains first (any order among themselves), then the config-entry
# template-helper domains (M10 -- also "helpers" from the dependency-ordering
# point of view: an automation/script may reference a template helper's
# entity id, so it must exist first, exactly like the storage helpers), then
# scripts, then automations (automations may reference scripts/helpers, so
# those must exist first).
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
    "template_number",
    "template_sensor",
    "template_binary_sensor",
    "template_select",
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
    category_warnings: list[str] = []  # M11: never fails/rolls back apply (I6)

    for entry in push_entries:
        identity = _identity_of(entry.object_key)

        if entry.action in (PlanAction.UPDATE, PlanAction.DELETE):
            remote_now = backend.list_remote(entry.kind).get(identity)
            remote_hash_now = None if remote_now is None else sha256_hash(remote_now)
            if remote_hash_now != entry.remote_hash_at_plan:
                # Drift since plan time: abort before writing this or anything
                # after it. Objects already applied this run are rolled back.
                return _abort(backend, entry, push_entries, outcomes, snapshots, applied)
            snapshots.append((entry.kind, identity, remote_now))
        else:  # CREATE
            # CREATE-collision drift detection (M5 review finding, MILESTONES M6
            # test 5): at plan time nothing existed under this identity, so a
            # CREATE carries no `remote_hash_at_plan`. If some object has since
            # materialized under that identity (a UI create, or a racing client),
            # a blind create would silently overwrite it — that is drift too, and
            # apply must abort before writing rather than clobber it.
            if identity in backend.list_remote(entry.kind):
                return _abort(backend, entry, push_entries, outcomes, snapshots, applied)
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

        if entry.action is PlanAction.CREATE:
            # M11: metadata-only, best-effort -- never raises past this call
            # (attempt_category_writeback catches everything internally) and
            # never affects `outcomes`/rollback for the object it just created.
            result = attempt_category_writeback(backend, entry.kind, identity, entry.source_path)
            if result.warning is not None:
                category_warnings.append(result.warning)

    new_manifest = _advance_manifest(manifest, backend, push_entries, synced_at)
    return ApplyResult(
        outcomes=outcomes,
        succeeded=True,
        manifest=new_manifest,
        category_warnings=category_warnings,
    )


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


def _abort(
    backend: Backend,
    entry: PlanEntry,
    push_entries: list[PlanEntry],
    outcomes: dict[str, ApplyOutcome],
    snapshots: list[tuple[str, str, dict[str, object] | None]],
    applied: list[str],
) -> ApplyResult:
    """Abort at ``entry`` (drift or CREATE-collision): nothing written past what
    was already applied, and everything applied this run is rolled back."""
    outcomes[entry.object_key] = ApplyOutcome.ABORTED
    _mark_remaining_aborted(push_entries, entry, outcomes)
    _rollback(backend, snapshots)
    for key in applied:
        outcomes[key] = ApplyOutcome.ROLLED_BACK
    return ApplyResult(outcomes=outcomes, succeeded=False, manifest=None)


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
            entry_id=_entry_id_of(backend, entry.kind, identity),
        )
    return Manifest(
        synced_at=synced_at if synced_at is not None else manifest.synced_at,
        ha_version=manifest.ha_version,
        objects=new_objects,
    )


def _entry_id_of(backend: Backend, kind: str, identity: str) -> str | None:
    """The config entry's HA-assigned `entry_id` for a template-helper kind
    (docs/ha-api-notes.md §26.5), tracked in the manifest -- `None` for every
    other kind. `entry_id_for` is NOT part of the frozen `Backend` Protocol
    (F2): it's an additive, defensively-probed extra method both `FakeBackend`
    and `DirectBackend` happen to expose, the same pattern
    `fetch_registry_snapshot` already established for non-F2 backend extras.
    """
    lookup = getattr(backend, "entry_id_for", None)
    if lookup is None:
        return None
    result = lookup(kind, identity)
    return str(result) if result is not None else None
