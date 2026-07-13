"""F2 — the plan/apply data model (`hassle.sync`) — DESIGN §8.1/§8.2.

Covers the shape of `PlanAction`, `Plan`/`PlanEntry`, `Conflict`/`ConflictKind`,
`Manifest`/`ManifestEntry`, and `ApplyResult`, independent of the plan/apply/pull
engines themselves (those get their own test files). This is the "F2 skeleton"
freeze-point contract: M6/M7 depend on these shapes existing and behaving as
documented in docs/backend.md.
"""

from __future__ import annotations

from hassle.ir.canonical import sha256_hash
from hassle.sync import (
    ApplyOutcome,
    ApplyResult,
    Conflict,
    ConflictKind,
    Manifest,
    ManifestEntry,
    Plan,
    PlanAction,
    PlanEntry,
)


def test_plan_action_has_exact_table_rows() -> None:
    """DESIGN §8.2's table has exactly these 8 distinct action kinds."""
    names = {member.value for member in PlanAction}
    assert names == {
        "noop",
        "update",
        "delete",
        "refresh",
        "conflict",
        "drop",
        "create",
        "adopt",
    }


def test_conflict_kind_has_three_subtypes() -> None:
    names = {member.value for member in ConflictKind}
    assert names == {
        "both_edited",
        "deleted_locally_edited_remotely",
        "edited_locally_deleted_remotely",
    }


def test_conflict_carries_base_local_remote_and_key() -> None:
    conflict = Conflict(
        object_key="automation:hall",
        kind=ConflictKind.BOTH_EDITED,
        base={"alias": "base"},
        local={"alias": "local"},
        remote={"alias": "remote"},
    )
    assert conflict.object_key == "automation:hall"
    assert conflict.kind is ConflictKind.BOTH_EDITED
    assert conflict.base == {"alias": "base"}
    assert conflict.local == {"alias": "local"}
    assert conflict.remote == {"alias": "remote"}


def test_conflict_allows_none_for_deleted_side() -> None:
    # "deleted locally, edited remotely" — local side is None (no local config).
    conflict = Conflict(
        object_key="script:foo",
        kind=ConflictKind.DELETED_LOCALLY_EDITED_REMOTELY,
        base={"alias": "base"},
        local=None,
        remote={"alias": "remote-edit"},
    )
    assert conflict.local is None


def test_plan_entry_minimal_noop() -> None:
    entry = PlanEntry(object_key="automation:hall", kind="automation", action=PlanAction.NOOP)
    assert entry.object_key == "automation:hall"
    assert entry.action is PlanAction.NOOP
    assert entry.conflict is None


def test_plan_entry_conflict_carries_conflict_payload() -> None:
    conflict = Conflict(
        object_key="automation:hall",
        kind=ConflictKind.BOTH_EDITED,
        base={"a": 1},
        local={"a": 2},
        remote={"a": 3},
    )
    entry = PlanEntry(
        object_key="automation:hall",
        kind="automation",
        action=PlanAction.CONFLICT,
        conflict=conflict,
    )
    assert entry.conflict is conflict


def test_plan_is_a_list_of_entries() -> None:
    entries = [
        PlanEntry(object_key="automation:a", kind="automation", action=PlanAction.NOOP),
        PlanEntry(object_key="script:b", kind="script", action=PlanAction.UPDATE, local={"x": 1}),
    ]
    plan = Plan(entries=entries)
    assert list(plan.entries) == entries
    assert len(plan) == 2
    assert plan[0].object_key == "automation:a"


def test_plan_entries_by_action_helper() -> None:
    entries = [
        PlanEntry(object_key="automation:a", kind="automation", action=PlanAction.NOOP),
        PlanEntry(object_key="script:b", kind="script", action=PlanAction.UPDATE, local={"x": 1}),
        PlanEntry(object_key="script:c", kind="script", action=PlanAction.DELETE, base={"x": 1}),
    ]
    plan = Plan(entries=entries)
    updates = plan.entries_with_action(PlanAction.UPDATE)
    assert [e.object_key for e in updates] == ["script:b"]


def test_manifest_entry_shape_matches_design_8_1() -> None:
    entry = ManifestEntry(
        source="automations/hallway.py",
        compiled_hash=sha256_hash({"alias": "x"}),
        kind="dsl",
    )
    assert entry.source == "automations/hallway.py"
    assert entry.compiled_hash.startswith("sha256:")
    assert entry.kind == "dsl"


def test_manifest_shape_matches_design_8_1() -> None:
    manifest = Manifest(
        synced_at="2026-07-03T18:20:00Z",
        ha_version="2026.6.3",
        objects={
            "automation:hall_light_on_motion": ManifestEntry(
                source="automations/hallway.py",
                compiled_hash=sha256_hash({"alias": "x"}),
                kind="dsl",
            ),
        },
    )
    assert manifest.synced_at == "2026-07-03T18:20:00Z"
    assert manifest.ha_version == "2026.6.3"
    assert "automation:hall_light_on_motion" in manifest.objects


def test_manifest_never_calls_wall_clock_itself() -> None:
    # Manifest is a plain data model: synced_at is whatever the caller supplies,
    # never computed internally (R8 — no wall-clock in core logic).
    m1 = Manifest(synced_at="frozen-value", ha_version="1.0", objects={})
    assert m1.synced_at == "frozen-value"


def test_manifest_stable_serialization_roundtrip() -> None:
    manifest = Manifest(
        synced_at="2026-07-03T18:20:00Z",
        ha_version="2026.6.3",
        objects={
            "input_boolean:guest_mode": ManifestEntry(
                source="helpers/guest.py",
                compiled_hash=sha256_hash({"name": "Guest"}),
                kind="dsl",
            ),
        },
    )
    dumped = manifest.to_json_dict()
    restored = Manifest.from_json_dict(dumped)
    assert restored == manifest


def test_manifest_canonical_json_is_stable() -> None:
    manifest = Manifest(synced_at="t", ha_version="v", objects={})
    assert manifest.canonical_json() == manifest.canonical_json()


def test_apply_result_records_outcome_per_object() -> None:
    result = ApplyResult(
        outcomes={
            "automation:hall": ApplyOutcome.SUCCEEDED,
            "script:foo": ApplyOutcome.ROLLED_BACK,
        },
        succeeded=False,
        manifest=None,
    )
    assert result.outcomes["automation:hall"] is ApplyOutcome.SUCCEEDED
    assert result.outcomes["script:foo"] is ApplyOutcome.ROLLED_BACK
    assert result.succeeded is False
    assert result.manifest is None


def test_ha_normalization_drift_is_not_an_update() -> None:
    """Owner field report (29 perpetually-spurious plan updates): HA's
    storage collections store input_number numerics as floats and fill
    mode='slider'; timers store duration as H:MM:SS (no hour zero-pad) and
    fill restore=False. A local config differing ONLY by those is the same
    object -- NOOP, never update (and never a conflict against a stale
    base hash)."""
    from hassle.ir.canonical import sha256_hash
    from hassle.sync.models import Manifest, ManifestEntry, PlanAction
    from hassle.sync.plan import compute_plan

    local_number = {"id": "lux", "name": "Lux", "min": 50, "max": 1000, "step": 10}
    remote_number = {
        "id": "lux",
        "name": "Lux",
        "min": 50.0,
        "max": 1000.0,
        "step": 10.0,
        "mode": "slider",
    }
    local_timer = {"id": "grace", "name": "Grace", "duration": "00:30:00"}
    remote_timer = {
        "id": "grace",
        "name": "Grace",
        "duration": "0:30:00",
        "restore": False,
    }
    manifest = Manifest(
        synced_at="t",
        ha_version="v",
        objects={
            "input_number:lux": ManifestEntry(
                source="x.py", compiled_hash=sha256_hash(local_number), kind="dsl"
            ),
            "timer:grace": ManifestEntry(
                source="x.py", compiled_hash=sha256_hash(local_timer), kind="dsl"
            ),
        },
    )
    plan = compute_plan(
        manifest=manifest,
        local_objects={
            "input_number:lux": ("input_number", local_number),
            "timer:grace": ("timer", local_timer),
        },
        remote_objects={
            "input_number:lux": ("input_number", remote_number),
            "timer:grace": ("timer", remote_timer),
        },
    )
    actions = {e.object_key: e.action for e in plan.entries}
    assert actions["input_number:lux"] is PlanAction.NOOP
    assert actions["timer:grace"] is PlanAction.NOOP


def test_real_helper_changes_still_update() -> None:
    from hassle.ir.canonical import sha256_hash
    from hassle.sync.models import Manifest, ManifestEntry, PlanAction
    from hassle.sync.plan import compute_plan

    from hassle.ir.canonical import storage_canonical

    local = {"id": "lux", "name": "Lux", "min": 40, "max": 1000, "step": 10}  # min edited
    remote = {
        "id": "lux",
        "name": "Lux",
        "min": 50.0,
        "max": 1000.0,
        "step": 10.0,
        "mode": "slider",
    }
    base = {"id": "lux", "name": "Lux", "min": 50, "max": 1000, "step": 10}
    manifest = Manifest(
        synced_at="t",
        ha_version="v",
        objects={
            "input_number:lux": ManifestEntry(
                source="x.py",
                # Post-fix manifests record CANONICAL hashes (push/pull both).
                compiled_hash=sha256_hash(storage_canonical("input_number", base)),
                kind="dsl",
            )
        },
    )
    plan = compute_plan(
        manifest=manifest,
        local_objects={"input_number:lux": ("input_number", local)},
        remote_objects={"input_number:lux": ("input_number", remote)},
    )
    [entry] = plan.entries
    assert entry.action is PlanAction.UPDATE
