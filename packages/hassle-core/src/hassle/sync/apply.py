"""The apply engine — `apply_plan` — DESIGN §8.2 (push-side actions).

Executes the push-side actions of a `Plan` (`create`/`update`/`delete`)
against a `Backend`, in dependency order **helpers -> scripts -> automations**
(DESIGN §8.2, docs/internals/ha-api-notes.md §11), with two safety mechanisms:

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
(no wall-clock in core logic) — it's supplied by the caller, defaulting to
the incoming manifest's own value if the caller doesn't advance it explicitly.

**Category write-back on CREATE.** Immediately after a CREATE succeeds
for an automation/script, `hassle.sync.category_writeback.
attempt_category_writeback` is given a chance to assign the HA UI category
implied by `PlanEntry.source_path` (DESIGN §7.3's placement, run in reverse).
This never affects apply's own success/rollback bookkeeping (it's pure
metadata, and a failure here is surfaced as a warning in
`ApplyResult.category_warnings`, never an aborted/rolled-back object) and is
never attempted for any action besides a freshly-succeeded CREATE.

**Category-on-move sync on UPDATE.** Immediately after an
UPDATE succeeds, `hassle.sync.category_move.sync_category_on_move` three-way
compares the object's local category (derived from `PlanEntry.source_path`),
the manifest's recorded base category (`ManifestEntry.category`), and the
live remote category, and pushes a category reassignment if the bundle moved
the object to a different category file since base. Like the write-back
above, this is metadata-only and never affects `outcomes`/rollback for the
object's own content update; a conflict (both sides changed, to different
values) is reported via `ApplyResult.category_conflicts` (no local or UI
edit is ever silently lost) and leaves the manifest's base category UNCHANGED
so the next plan/push surfaces the identical conflict again.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from hassle.backend.protocol import Backend
from hassle.ir.canonical import sha256_hash, storage_canonical
from hassle.ir.keys import BLUEPRINT_KIND
from hassle.sync.category_move import local_category_for_source_path, sync_category_on_move
from hassle.sync.category_writeback import (
    _SCOPE_FOR_KIND,  # pyright: ignore[reportPrivateUsage]
    attempt_category_writeback,
)
from hassle.sync.models import (
    ApplyOutcome,
    ApplyResult,
    Manifest,
    ManifestEntry,
    Plan,
    PlanAction,
    PlanEntry,
)

# Push-side apply order (DESIGN §8.2 / docs/internals/ha-api-notes.md §11): storage
# helper domains first (any order among themselves), then the config-entry
# template-helper and group-helper domains -- also "helpers" from
# the dependency-ordering point of view: an automation/script may reference a
# template/group helper's entity id, so it must exist first, exactly like the
# storage helpers; a group may also nest another group's entity id, but that
# is still satisfied by "every config-entry helper before scripts/
# automations" since apply doesn't need a stricter order within the family --
# then scripts, then automations (automations may reference scripts/helpers,
# so those must exist first), then dashboards LAST (docs/internals/
# dashboards-design.md §4.2): a dashboard's cards reference entities produced
# by every other kind, but nothing references a dashboard -- an explicit
# tuple entry even though the sort-last fallback (`_kind_sort_key` below)
# would happen to put an unlisted kind here anyway, because the rule is
# "kinds are added to `_KIND_ORDER` explicitly", not "whatever falls out of
# the fallback is fine" (docs/internals/backend-protocol.md §3.1.1 step 6).
_KIND_ORDER = (
    # `blueprint` FIRST (docs/internals/blueprints-design.md §4.1): HA
    # validates an instance against its blueprint at instance-save time, so a
    # blueprint file has to exist before any automation that uses it is
    # written. This is the position for a blueprint CREATE/UPDATE only -- a
    # blueprint DELETE sorts dead last instead, see `_entry_sort_key`.
    "blueprint",
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
    "group_binary_sensor",
    "group_button",
    "group_cover",
    "group_event",
    "group_fan",
    "group_light",
    "group_lock",
    "group_media_player",
    "group_notify",
    "group_sensor",
    "group_switch",
    "group_valve",
    "script",
    "automation",
    "dashboard",
)


def _kind_sort_key(kind: str) -> int:
    try:
        return _KIND_ORDER.index(kind)
    except ValueError:
        return len(_KIND_ORDER)


#: Kinds whose apply position depends on the ACTION as well as the kind, with
#: DELETE sorting after every other row instead of at the kind's own rank.
#:
#: `blueprint` is the first and so far only member (docs/internals/
#: blueprints-design.md §4.2): an instance of a blueprint has to be deleted
#: BEFORE the blueprint it uses, which is the exact mirror of §4.1's "the
#: blueprint has to exist before its instances are written". One kind, two
#: opposite ends of the same apply -- so `_KIND_ORDER` alone cannot express it
#: and the sort key has to see the action.
#:
#: Making it a named set rather than an `if entry.kind == "blueprint"` keeps
#: the "new kinds are added explicitly" discipline `_KIND_ORDER` already
#: follows (docs/internals/backend-protocol.md §3.1.1 step 6).
_DELETE_LAST_KINDS = frozenset({"blueprint"})


def _entry_sort_key(kind: str, action: PlanAction) -> int:
    """Push-apply rank for one entry.

    A pure function of `(kind, action)`, and the ONLY place apply order is
    decided -- which is what makes `_rollback`'s reverse walk automatically
    correct: it replays `snapshots` (recorded in this order) backwards, so
    "blueprint deletes are undone first, blueprint creates last" holds by
    construction rather than by a second table that could drift out of step
    with this one.
    """
    if kind in _DELETE_LAST_KINDS and action is PlanAction.DELETE:
        return len(_KIND_ORDER)
    return _kind_sort_key(kind)


_PUSH_ACTIONS = (PlanAction.CREATE, PlanAction.UPDATE, PlanAction.DELETE)


class BlueprintStillInstantiatedError(Exception):
    """A plan deletes a blueprint the bundle still declares instances of
    (docs/internals/blueprints-design.md §4.2).

    Raised BEFORE any write happens. Letting the apply run would delete the
    blueprint and leave every surviving instance unloadable -- Home Assistant
    rejects an instance whose blueprint is missing at its next save, and there
    is no source read that could put the file back (§2.1).
    """

    def __init__(self, object_key: str, instances: list[str]) -> None:
        self.object_key = object_key
        self.instances = instances
        identity = object_key.partition(":")[2]
        named = ", ".join(f"`{key}`" for key in sorted(instances))
        super().__init__(
            f"This plan deletes the blueprint `{identity}`, but the bundle still "
            f"declares {len(instances)} automation(s) that use it: {named}. Home "
            f"Assistant validates an instance against its blueprint every time the "
            f"instance is saved, so removing the blueprint would leave those "
            f"automations unloadable -- and Home Assistant cannot serve a blueprint's "
            f"source back, so there would be no way to restore the file from HA. "
            f"Nothing was written. Fix: delete (or re-point) those automations in the "
            f"bundle first and push that, then remove the blueprint file in a second "
            f"push -- or restore `blueprints/{identity}` if deleting it was a mistake."
        )


def apply_plan(
    plan: Plan,
    backend: Backend,
    manifest: Manifest,
    *,
    synced_at: str | None = None,
    category_overrides: dict[str, str] | None = None,
    category_packages: frozenset[str] | None = None,
    on_progress: Callable[[int, int, PlanEntry], None] | None = None,
    blueprint_instances: dict[str, list[str]] | None = None,
) -> ApplyResult:
    """Apply the push-side actions of ``plan`` against ``backend``.

    ``category_overrides`` (additive): bundle-relative source
    path -> exact category display name, sourced from that file's `CATEGORY`
    module global (`hassle_cli.bundle_ops`/`cli.py` build this from the
    compiled bundle's `CompileResult.category_globals`). Keyed by
    `PlanEntry.source_path` -- `CATEGORY` is a per-FILE global, matching
    DESIGN §7.3's placement being per-file too, never per-object. Threaded
    straight to `attempt_category_writeback`'s `category_override` for the
    matching CREATE; a missing/absent entry behaves exactly like the
    `humanize_slug` fallback (byte-identical when no override is supplied at
    all).

    ``category_packages`` (additive): the bundle's CATEGORY PACKAGES --
    root-level directories holding an `__init__.py`, whose every module
    shares one category (`CompileResult.category_packages`). Threaded to
    `local_category_for_source_path`/`attempt_category_writeback` so an
    object declared in `automatic_hvac/climate.py` resolves to the
    `automatic_hvac` category exactly as a root-level `automatic_hvac.py`
    would. Omitting it reproduces pre-package behaviour byte for byte.

    ``on_progress`` (additive): called before each push entry is
    applied with ``(index, total, entry)`` (1-based) -- the CLI's visible
    heartbeat during a long apply. Never called for an empty plan.

    ``blueprint_instances`` (additive, docs/internals/blueprints-design.md §4):
    blueprint object key -> the object keys instantiating it, built from the
    compiled bundle by `hassle.blueprints.instances_by_blueprint`. It does two
    jobs, and both need information a `Plan` alone does not carry (an
    UNCHANGED instance is a `noop` row with no `local` body):

    - **§4.2's refusal.** A plan deleting a blueprint the bundle still
      instantiates raises `BlueprintStillInstantiatedError` before ANY write.
    - **§4.3's reload.** A blueprint UPDATE triggers `automation.reload` only
      when instances exist -- nothing to re-expand otherwise.

    Omitting it reproduces pre-blueprint behaviour byte for byte.
    """
    push_entries = [entry for entry in plan.entries if entry.action in _PUSH_ACTIONS]
    # Pre-flight, before the sort and before anything is written or even read:
    # a plan that would strand live instances is refused outright rather than
    # half-applied and rolled back (§4.2).
    _refuse_stranding_deletes(push_entries, blueprint_instances or {})
    push_entries.sort(key=lambda entry: _entry_sort_key(entry.kind, entry.action))

    outcomes: dict[str, ApplyOutcome] = {}
    # (kind, identity) -> snapshot of the pre-apply remote config (None if the
    # object didn't exist yet, e.g. a CREATE).
    snapshots: list[tuple[str, str, dict[str, object] | None, PlanAction]] = []
    applied: list[str] = []  # object_keys successfully applied, in apply order
    category_warnings: list[str] = []  # never fails/rolls back apply
    category_conflicts: list[str] = []  # never fails/rolls back apply
    blueprint_reloads: list[str] = []  # blueprint keys an automation.reload followed
    # object_key -> the category slug ManifestEntry.category should
    # advance to (never touched at all for an object not in this dict --
    # `_advance_manifest` then falls back to the existing manifest entry's
    # own `category`, e.g. a plain content-only UPDATE with no category
    # change, or a conflict/failure that must not silently advance the base).
    resolved_categories: dict[str, str | None] = {}

    for entry_index, entry in enumerate(push_entries, start=1):
        if on_progress is not None:
            on_progress(entry_index, len(push_entries), entry)
        identity = _identity_of(entry.object_key)

        if entry.action in (PlanAction.UPDATE, PlanAction.DELETE):
            remote_now = backend.list_remote(entry.kind).get(identity)
            remote_hash_now = (
                None
                if remote_now is None
                else sha256_hash(storage_canonical(entry.kind, remote_now))
            )
            if remote_hash_now != entry.remote_hash_at_plan:
                # Drift since plan time: abort before writing this or anything
                # after it. Objects already applied this run are rolled back.
                return _abort(backend, entry, push_entries, outcomes, snapshots, applied)
            snapshots.append((entry.kind, identity, remote_now, entry.action))
        else:  # CREATE
            # CREATE-collision drift detection: at plan time nothing existed
            # under this identity, so a
            # CREATE carries no `remote_hash_at_plan`. If some object has since
            # materialized under that identity (a UI create, or a racing client),
            # a blind create would silently overwrite it — that is drift too, and
            # apply must abort before writing rather than clobber it.
            if identity in backend.list_remote(entry.kind):
                return _abort(backend, entry, push_entries, outcomes, snapshots, applied)
            snapshots.append((entry.kind, identity, None, entry.action))

        try:
            _apply_one(backend, entry, identity)
        except BaseException as exc:
            outcomes[entry.object_key] = ApplyOutcome.FAILED
            _mark_remaining_aborted(push_entries, entry, outcomes, skip_first=True)
            rollback_failures = _rollback(backend, snapshots[:-1])
            for key in applied:
                outcomes[key] = ApplyOutcome.ROLLED_BACK
            for kind, stuck_identity, _error in rollback_failures:
                outcomes[f"{kind}:{stuck_identity}"] = ApplyOutcome.ROLLBACK_FAILED
            if not isinstance(exc, Exception):
                # KeyboardInterrupt/SystemExit mid-apply: roll back like any
                # other failure, then let the interrupt propagate. An
                # un-rolled-back partial push leaves the already-written
                # objects live in HA while the manifest keeps their PRE-push
                # bases -- the next plan then reports a false `both_edited`
                # conflict against the user's own pushed content once the
                # local side is edited again. Rollback is best-effort (a
                # second interrupt during
                # the rollback's own backend calls still escapes), and any
                # objects it could NOT restore are reported by the next
                # `hassle plan` rather than by this raise.
                raise
            failure_message = str(exc) if isinstance(exc, CreatedIdentityDivergedError) else None
            rollback_message = _rollback_failure_message(rollback_failures)
            if rollback_message is not None:
                failure_message = (
                    f"{failure_message} {rollback_message}" if failure_message else rollback_message
                )
            return ApplyResult(
                outcomes=outcomes,
                succeeded=False,
                manifest=None,
                failure_message=failure_message,
            )

        outcomes[entry.object_key] = ApplyOutcome.SUCCEEDED
        applied.append(entry.object_key)

        if entry.action is PlanAction.CREATE:
            # Metadata-only, best-effort -- never raises past this call
            # (attempt_category_writeback catches everything internally) and
            # never affects `outcomes`/rollback for the object it just created.
            override = None
            if category_overrides is not None and entry.source_path is not None:
                override = category_overrides.get(entry.source_path)
            result = attempt_category_writeback(
                backend,
                entry.kind,
                identity,
                entry.source_path,
                category_override=override,
                package_roots=category_packages,
            )
            if result.warning is not None:
                category_warnings.append(result.warning)
            elif result.attempted:
                # The category slug just assigned becomes this object's base
                # -- so a FUTURE local move away from it is correctly
                # detected as "local changed since base", not perpetually
                # invisible.
                resolved_categories[entry.object_key] = local_category_for_source_path(
                    entry.kind, entry.source_path, category_packages
                )

        elif entry.action is PlanAction.UPDATE and entry.kind == BLUEPRINT_KIND:
            # §4.3: HA does not re-expand already-loaded instances on
            # `blueprint/save` alone, so a bundle with live instances of this
            # blueprint needs an `automation.reload` to pick the new file up.
            # Only for an UPDATE (a CREATE cannot have instances expanded
            # against a file that did not exist) and only when the bundle
            # actually declares instances.
            if _reload_after_blueprint_update(backend, entry.object_key, blueprint_instances):
                blueprint_reloads.append(entry.object_key)

        elif entry.action is PlanAction.UPDATE:
            # Category-on-move sync -- metadata-only,
            # best-effort, never affects `outcomes`/rollback for the object's
            # own content update that just succeeded (no local or UI edit is
            # ever silently lost). Only attempted
            # when there IS a recorded manifest entry for this object: an
            # UPDATE with no manifest entry at all means there is no known
            # base to three-way against (in practice `compute_plan` never
            # produces this combination -- UPDATE always implies a manifest
            # entry -- but apply_plan accepts hand-built plans too, and the
            # safe, conservative choice with zero sync history on record is
            # to take no action rather than force-assign based on placement
            # alone, mirroring `compute_plan`'s own "no base -> CREATE/ADOPT,
            # never UPDATE" rule).
            existing_entry = manifest.objects.get(entry.object_key)
            if existing_entry is not None:
                local_category = local_category_for_source_path(
                    entry.kind, entry.source_path, category_packages
                )
                move_result = sync_category_on_move(
                    backend,
                    entry.kind,
                    identity,
                    local_category=local_category,
                    base_category=existing_entry.category,
                    scope=_SCOPE_FOR_KIND.get(entry.kind),
                )
                if move_result.warning is not None:
                    category_warnings.append(move_result.warning)
                if move_result.conflict_message is not None:
                    category_conflicts.append(move_result.conflict_message)
                if not move_result.base_unchanged:
                    resolved_categories[entry.object_key] = move_result.new_base_category

    new_manifest = _advance_manifest(
        manifest, backend, push_entries, synced_at, resolved_categories
    )
    return ApplyResult(
        outcomes=outcomes,
        succeeded=True,
        manifest=new_manifest,
        category_warnings=category_warnings,
        category_conflicts=category_conflicts,
        blueprint_reloads=blueprint_reloads,
    )


def _refuse_stranding_deletes(
    push_entries: list[PlanEntry], blueprint_instances: dict[str, list[str]]
) -> None:
    """Refuse a plan that deletes a blueprint the bundle still instantiates.

    docs/internals/blueprints-design.md §4.2. Structural rather than advisory:
    it runs on the raw entry list before the sort and before the first backend
    call, so there is no half-applied state to roll back and no window in which
    the blueprint is gone while its instances are still live.
    """
    for entry in push_entries:
        if entry.kind != BLUEPRINT_KIND or entry.action is not PlanAction.DELETE:
            continue
        instances = blueprint_instances.get(entry.object_key)
        if instances:
            raise BlueprintStillInstantiatedError(entry.object_key, instances)


def _reload_after_blueprint_update(
    backend: Backend,
    object_key: str,
    blueprint_instances: dict[str, list[str]] | None,
) -> bool:
    """Issue `automation.reload` after a blueprint update, if warranted.

    TODO(blueprints-design §4.3 — marked for empirical confirmation): the
    design records "HA does not re-expand live instances on `blueprint/save`
    alone" as **believed, not probed** (the 2026-08-10 session captured every
    other §2 shape but not this one; ha-api-notes §40.4). The stated behavior is
    implemented here and the owner will verify live. Either outcome is safe --
    if HA does re-expand on its own, this reload is redundant but harmless --
    so the finding, once captured, changes at most whether this call stays.

    `reload_automations` is additive and NOT part of the frozen `Backend`
    Protocol; it is probed with `getattr`, the same pattern `entry_id_for` and
    `fetch_registry_snapshot` use, so a backend without it simply does not
    reload. Returns whether a reload was actually issued.
    """
    if not blueprint_instances or not blueprint_instances.get(object_key):
        return False
    reload = getattr(backend, "reload_automations", None)
    if reload is None:
        return False
    reload()
    return True


def _identity_of(object_key: str) -> str:
    _, _, identity = object_key.partition(":")
    return identity


#: Kinds whose create is exempt from the `CreatedIdentityDivergedError`
#: guard because the caller, not HA, keys the object AND the id it keys by
#: is an intrinsic body field the caller demonstrably sent (an automation's
#: `id`, `_build_automation`). `script` is deliberately NOT in this set:
#: a script's object_id is EXTRINSIC (`ScriptConfig` has no `id` field), so
#: "caller-keyed" says nothing about whether the object_id actually reached
#: the backend -- it did not, for the whole of M5-M11, and the exemption is
#: what made that silent (docs/internals/ha-api-notes.md §17.5;
#: `tests/test_script_create_object_id.py`). `dashboard` joins `automation`
#: here (docs/internals/dashboards-design.md §4.1): identity is
#: `meta.url_path` (or the `"default"` sentinel when `meta` is null), always
#: an intrinsic part of the envelope the caller sends -- never HA-assigned,
#: so it can never diverge the way a slugified helper name can.
#: `blueprint` joins them (docs/internals/blueprints-design.md §1): identity is
#: `domain` + `path`, both intrinsic to the body the caller sends and never
#: HA-assigned -- the path IS the address, so it cannot diverge.
_CALLER_KEYED_KINDS = frozenset({"automation", "dashboard", "blueprint"})


def _create_body(kind: str, identity: str, local: dict[str, Any]) -> dict[str, Any]:
    """The config body to hand `Backend.create`, carrying the object_id for
    the kinds whose identity is EXTRINSIC to the body.

    `Backend.create(kind, config)` takes no identity argument -- the identity
    has to ride inside `config`, exactly as `Backend.update` already forwards
    it (`{**config, "id": identity}`). For automations and helpers that is
    free: `id` is an intrinsic field their compiled body already carries. A
    script's object_id is extrinsic -- it belongs in the REST path
    (`/api/config/script/config/{object_id}`, docs/internals/ha-api-notes.md
    §3) and never in the body, so `ScriptConfig` has no `id` field and
    `_build_script` keeps the declared id out. Without this injection both
    backends fall through to their "no id supplied" fallback and invent one
    by slugifying `alias` -- which is exactly how a pushed
    `@script(id="dining_bid_manual", alias="Dining Bid: Manual Hold")` became
    `script.dining_bid_manual_hold` in a real home, breaking its callers
    (§17.5).

    Both backends strip `id` back out before it reaches storage
    (`DirectBackend._awrite_script` before the POST, `FakeBackend._stored_body`
    before the store), so the stored/read-back body keeps HA's real shape --
    no `id` key -- and local-vs-remote hashing is unaffected.
    """
    if kind == "script":
        return {**local, "id": identity}
    return local


class CreatedIdentityDivergedError(Exception):
    """`backend.create` derived a different identity than the bundle
    declares (HA ignores a helper create's supplied id and slugifies its
    NAME). Left alone, the manifest entry never matches the remote object
    and every subsequent push silently creates another copy (e.g. `_degf`,
    `_degf_2`, `_degf_3`). The just-created object is rolled back before
    this is raised."""

    def __init__(self, declared: str, actual: str, source_path: str | None = None) -> None:
        self.declared = declared
        self.actual = actual
        where = f" (declared in {source_path})" if source_path else ""
        super().__init__(
            f"Home Assistant derived the id `{actual}` for this new object, but the "
            f"bundle declares `{declared}`{where} -- the two can never link up, so "
            f"pushing again would create a duplicate every time. The created object "
            f"was removed. Fix: change the declaration's id to `{actual}` (or rename "
            f"it so its name slugifies to `{declared}`), then push again."
        )


def _apply_one(backend: Backend, entry: PlanEntry, identity: str) -> None:
    if entry.action is PlanAction.CREATE:
        assert entry.local is not None
        actual = backend.create(entry.kind, _create_body(entry.kind, identity, entry.local))
        # Every kind whose identity HA assigns (storage helpers slugify the
        # name; template helpers likewise, docs/internals/ha-api-notes.md
        # §17.5/§26.6) can diverge -- and so can a script, whose object_id is
        # extrinsic to the body (`_create_body`): if it ever fails to reach
        # the backend again, this guard turns the duplicate-forever failure
        # into a loud, rolled-back error instead of a silently wrong entity
        # id. Only an automation is exempt: it is keyed by an intrinsic `id`
        # field its own compiled body always carries.
        if entry.kind not in _CALLER_KEYED_KINDS and actual != identity:
            backend.delete(entry.kind, actual)
            raise CreatedIdentityDivergedError(identity, actual, entry.source_path)
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
    snapshots: list[tuple[str, str, dict[str, object] | None, PlanAction]],
    applied: list[str],
) -> ApplyResult:
    """Abort at ``entry`` (drift or CREATE-collision): nothing written past what
    was already applied, and everything applied this run is rolled back."""
    outcomes[entry.object_key] = ApplyOutcome.ABORTED
    _mark_remaining_aborted(push_entries, entry, outcomes)
    rollback_failures = _rollback(backend, snapshots)
    for key in applied:
        outcomes[key] = ApplyOutcome.ROLLED_BACK
    for kind, stuck_identity, _error in rollback_failures:
        outcomes[f"{kind}:{stuck_identity}"] = ApplyOutcome.ROLLBACK_FAILED
    return ApplyResult(
        outcomes=outcomes,
        succeeded=False,
        manifest=None,
        failure_message=_rollback_failure_message(rollback_failures),
    )


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


def _rollback(
    backend: Backend,
    snapshots: list[tuple[str, str, dict[str, object] | None, PlanAction]],
) -> list[tuple[str, str, str]]:
    """Restore in reverse order of application. Returns the steps that could
    NOT be restored as ``(kind, identity, error)`` -- a failing step never
    aborts the remaining restores: without this guard, the first rollback
    step to raise would leave every earlier object un-restored, with a raw
    traceback as the only output.

    Config-entry caveat: a recreate here gets a FRESH
    entry_id from HA (docs/internals/ha-api-notes.md §26.3) while the on-disk manifest
    -- unchanged on a failed apply -- still records the old one. Not silent:
    the next `hassle plan` (which the failure message directs the user to
    run) re-reads entry ids from the live registry and surfaces any
    divergence; slug-keyed kinds are unaffected (same identity, §17.5).

    **Blueprint caveat (docs/internals/blueprints-design.md §4, ha-api-notes
    §40.5).** A blueprint UPDATE or DELETE **cannot be rolled back at all**:
    the snapshot this function restores from is what `list_remote` returned,
    and for a blueprint that is metadata only -- Home Assistant has no command
    that serves a blueprint's source back (§2.1), so the previous document
    exists nowhere the apply engine can reach. Rather than send a sourceless
    body and let the backend fail with a confusing schema error, those two
    cases are reported as purpose-built rollback failures naming the file and
    the real fix (restore it from git and push again). This is loud, per I6 --
    never silent -- and it is narrow: a blueprint CREATE rolls back perfectly
    (delete it back out), and the apply ordering means a blueprint DELETE is
    the last thing written, so nothing applied after one can fail and strand
    it."""
    failures: list[tuple[str, str, str]] = []
    for kind, identity, previous, action in reversed(snapshots):
        if kind == BLUEPRINT_KIND and previous is not None:
            # `previous` is the metadata-only remote body; there is no source
            # in it and no way to fetch one. See the caveat above.
            failures.append((kind, identity, _blueprint_rollback_reason(identity, action)))
            continue
        try:
            if previous is None:
                # It didn't exist before (this was a CREATE) -> delete it out.
                backend.delete(kind, identity)
            elif action is PlanAction.DELETE:
                # The apply DELETED it: an update against a now-missing object
                # errors on real HA -- restore by recreating. Slug-keyed kinds
                # land back on the same identity (§17.5); config-entry kinds
                # get a fresh entry_id (the documented rollback caveat,
                # docs/internals/ha-api-notes.md §26.3). `_create_body`
                # carries the object_id for a script: the snapshot being
                # restored is HA's read-back body, which correctly has no
                # `id`, so without it a rolled-back delete would resurrect
                # the script at its alias slug rather than where it was.
                backend.create(kind, _create_body(kind, identity, previous))  # type: ignore[arg-type]
            else:
                backend.update(kind, identity, previous)
        except Exception as exc:
            failures.append((kind, identity, str(exc)))
    return failures


def _blueprint_rollback_reason(identity: str, action: PlanAction) -> str:
    what = (
        "its previous content was overwritten" if action is PlanAction.UPDATE else "it was deleted"
    )
    return (
        f"{what} and Home Assistant cannot serve a blueprint's source back, so the "
        f"old version of `blueprints/{identity}` could not be restored -- recover it "
        f"from git (it is the copy of record) and push again"
    )


def _rollback_failure_message(failures: list[tuple[str, str, str]]) -> str | None:
    if not failures:
        return None
    stuck = "; ".join(f"{kind}:{identity} ({error})" for kind, identity, error in failures)
    return (
        f"rollback could not restore {stuck} -- Home Assistant may now hold a "
        "partially applied plan for these objects. Fix: run `hassle plan` to "
        "see the actual remote state, then re-run `hassle push` (resolving any "
        "conflicts) once the underlying backend error is addressed."
    )


def _advance_manifest(
    manifest: Manifest,
    backend: Backend,
    push_entries: list[PlanEntry],
    synced_at: str | None,
    resolved_categories: dict[str, str | None],
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
        if entry.kind == BLUEPRINT_KIND:
            # docs/internals/blueprints-design.md §3: the manifest's stored
            # hash for a blueprint is "the hash of the LOCAL file at last
            # push", NOT of anything remote. `current` here is the
            # metadata-only body `list_remote` can see (§2.1); recording its
            # hash would make every subsequent plan compare an authored
            # document against a metadata hash and report an endless update.
            new_objects[entry.object_key] = ManifestEntry(
                source=entry.source_path
                if entry.source_path is not None
                else (existing.source if existing is not None else None),
                compiled_hash=sha256_hash(entry.local) if entry.local is not None else "",
                kind="blueprint",
            )
            continue
        if entry.object_key in resolved_categories:
            category = resolved_categories[entry.object_key]
        else:
            # No category change this run (a plain content-only UPDATE, a
            # conflict, or a category-sync failure) -- carry the existing
            # base forward unchanged: never silently advance past a
            # conflict/failure (no local or UI edit is ever silently lost).
            category = existing.category if existing is not None else None
        new_objects[entry.object_key] = ManifestEntry(
            source=existing.source if existing is not None else None,
            compiled_hash=sha256_hash(storage_canonical(entry.kind, current)),
            kind=existing.kind if existing is not None else "dsl",
            entry_id=_entry_id_of(backend, entry.kind, identity),
            category=category,
        )
    return Manifest(
        synced_at=synced_at if synced_at is not None else manifest.synced_at,
        ha_version=manifest.ha_version,
        objects=new_objects,
    )


def _entry_id_of(backend: Backend, kind: str, identity: str) -> str | None:
    """The config entry's HA-assigned `entry_id` for a template-helper kind
    (docs/internals/ha-api-notes.md §26.5), tracked in the manifest -- `None` for every
    other kind. `entry_id_for` is NOT part of the frozen `Backend` Protocol:
    it's an additive, defensively-probed extra method both `FakeBackend`
    and `DirectBackend` happen to expose, the same pattern
    `fetch_registry_snapshot` already established for non-protocol backend
    extras.
    """
    lookup = getattr(backend, "entry_id_for", None)
    if lookup is None:
        return None
    result = lookup(kind, identity)
    return str(result) if result is not None else None
