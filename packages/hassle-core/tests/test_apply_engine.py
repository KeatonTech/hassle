"""Apply engine — push-side plan execution against Backend (DESIGN §8.2).

Covers:
- test_apply_reverifies_hashes (MILESTONES M5 test 3): remote drifts between
  plan and apply -> abort, nothing written.
- test_apply_order_and_rollback (MILESTONES M5 test 4): helpers -> scripts ->
  automations order; injected failure at each step -> previously-applied
  objects restored from snapshot; FakeBackend final state == initial state.
- test_manifest_updates_only_on_success (MILESTONES M5 test 6).
"""

from __future__ import annotations

from typing import Any

import pytest

from hassle.backend.fake import FakeBackend
from hassle.ir.canonical import sha256_hash
from hassle.sync import ApplyOutcome, Manifest, ManifestEntry, Plan, PlanAction, PlanEntry
from hassle.sync.apply import apply_plan


def _plan_entry_update(
    object_key: str, kind: str, local: dict[str, Any], plan_hash: str
) -> PlanEntry:
    return PlanEntry(
        object_key=object_key,
        kind=kind,
        action=PlanAction.UPDATE,
        local=local,
        remote_hash_at_plan=plan_hash,
    )


def test_apply_reverifies_hashes_aborts_on_drift() -> None:
    backend = FakeBackend()
    identity = backend.create("automation", {"id": "a1", "alias": "Original"})
    original_remote = backend.list_remote("automation")[identity]
    plan_time_hash = sha256_hash(original_remote)

    # Remote drifts AFTER plan was computed but BEFORE apply runs.
    backend.update("automation", identity, {"id": "a1", "alias": "Drifted by UI"})
    backend.reset_write_tracking()

    plan = Plan(
        entries=[
            _plan_entry_update(
                "automation:a1", "automation", {"id": "a1", "alias": "Local Edit"}, plan_time_hash
            )
        ]
    )
    manifest = Manifest(synced_at="t", ha_version="v", objects={})
    result = apply_plan(plan, backend, manifest)

    assert result.succeeded is False
    # Nothing further written: the drifted object's remote value is unchanged
    # from the (already-drifted) state at abort time.
    assert backend.writes_since_reset() == 0
    assert backend.list_remote("automation")[identity]["alias"] == "Drifted by UI"


def test_apply_succeeds_when_remote_hash_matches_plan_time() -> None:
    backend = FakeBackend()
    identity = backend.create("automation", {"id": "a1", "alias": "Original"})
    plan_time_hash = sha256_hash(backend.list_remote("automation")[identity])

    plan = Plan(
        entries=[
            _plan_entry_update(
                "automation:a1", "automation", {"id": "a1", "alias": "Local Edit"}, plan_time_hash
            )
        ]
    )
    manifest = Manifest(synced_at="t", ha_version="v", objects={})
    result = apply_plan(plan, backend, manifest)

    assert result.succeeded is True
    assert backend.list_remote("automation")[identity]["alias"] == "Local Edit"


def test_apply_order_is_helpers_then_scripts_then_automations() -> None:
    backend = FakeBackend()
    order: list[str] = []

    original_create = backend.create

    def tracking_create(kind: str, config: dict[str, Any]) -> str:
        order.append(kind)
        return original_create(kind, config)

    backend.create = tracking_create  # type: ignore[method-assign]

    plan = Plan(
        entries=[
            PlanEntry(
                object_key="automation:a1",
                kind="automation",
                action=PlanAction.CREATE,
                local={"id": "a1", "alias": "A"},
            ),
            PlanEntry(
                object_key="script:s1",
                kind="script",
                action=PlanAction.CREATE,
                local={"alias": "S"},
            ),
            PlanEntry(
                object_key="input_boolean:b1",
                kind="input_boolean",
                action=PlanAction.CREATE,
                local={"name": "B"},
            ),
        ]
    )
    manifest = Manifest(synced_at="t", ha_version="v", objects={})
    result = apply_plan(plan, backend, manifest)

    assert result.succeeded is True
    assert order == ["input_boolean", "script", "automation"]


def test_apply_order_and_rollback_restores_previously_applied_objects() -> None:
    backend = FakeBackend()
    helper_id = backend.create("input_boolean", {"name": "Helper Original"})
    script_id = backend.create("script", {"alias": "Script Original"})
    automation_id = backend.create("automation", {"id": "a1", "alias": "Automation Original"})

    initial_snapshot = {
        "input_boolean": dict(backend.list_remote("input_boolean")),
        "script": dict(backend.list_remote("script")),
        "automation": dict(backend.list_remote("automation")),
    }

    helper_hash = sha256_hash(backend.list_remote("input_boolean")[helper_id])
    script_hash = sha256_hash(backend.list_remote("script")[script_id])
    automation_hash = sha256_hash(backend.list_remote("automation")[automation_id])

    plan = Plan(
        entries=[
            PlanEntry(
                object_key=f"input_boolean:{helper_id}",
                kind="input_boolean",
                action=PlanAction.UPDATE,
                local={"name": "Helper Updated"},
                remote_hash_at_plan=helper_hash,
            ),
            PlanEntry(
                object_key=f"script:{script_id}",
                kind="script",
                action=PlanAction.UPDATE,
                local={"alias": "Script Updated"},
                remote_hash_at_plan=script_hash,
            ),
            PlanEntry(
                object_key=f"automation:{automation_id}",
                kind="automation",
                action=PlanAction.UPDATE,
                local={"id": automation_id, "alias": "FAIL_ME"},
                remote_hash_at_plan=automation_hash,
            ),
        ]
    )
    manifest = Manifest(synced_at="t", ha_version="v", objects={})

    original_update = backend.update

    def failing_update(kind: str, identity: str, config: dict[str, Any]) -> None:
        if config.get("alias") == "FAIL_ME":
            raise RuntimeError("simulated backend failure")
        original_update(kind, identity, config)

    backend.update = failing_update  # type: ignore[method-assign]

    result = apply_plan(plan, backend, manifest)

    assert result.succeeded is False
    assert result.outcomes[f"input_boolean:{helper_id}"] is ApplyOutcome.ROLLED_BACK
    assert result.outcomes[f"script:{script_id}"] is ApplyOutcome.ROLLED_BACK
    assert result.outcomes[f"automation:{automation_id}"] is ApplyOutcome.FAILED

    # Final state == initial state (rollback via Backend calls).
    assert backend.list_remote("input_boolean") == initial_snapshot["input_boolean"]
    assert backend.list_remote("script") == initial_snapshot["script"]
    assert backend.list_remote("automation") == initial_snapshot["automation"]


@pytest.mark.parametrize("fail_at", ["input_boolean", "script", "automation"])
def test_apply_rollback_at_each_step(fail_at: str) -> None:
    backend = FakeBackend()
    helper_id = backend.create("input_boolean", {"name": "Helper Original"})
    script_id = backend.create("script", {"alias": "Script Original"})
    automation_id = backend.create("automation", {"id": "a1", "alias": "Automation Original"})

    initial_snapshot = {
        "input_boolean": dict(backend.list_remote("input_boolean")),
        "script": dict(backend.list_remote("script")),
        "automation": dict(backend.list_remote("automation")),
    }

    def hash_of(kind: str, identity: str) -> str:
        return sha256_hash(backend.list_remote(kind)[identity])

    def make_entry(kind: str, identity: str, local: dict[str, Any]) -> PlanEntry:
        return PlanEntry(
            object_key=f"{kind}:{identity}",
            kind=kind,
            action=PlanAction.UPDATE,
            local=local,
            remote_hash_at_plan=hash_of(kind, identity),
        )

    plan = Plan(
        entries=[
            make_entry(
                "input_boolean",
                helper_id,
                {"name": "FAIL" if fail_at == "input_boolean" else "Helper Updated"},
            ),
            make_entry(
                "script", script_id, {"alias": "FAIL" if fail_at == "script" else "Script Updated"}
            ),
            make_entry(
                "automation",
                automation_id,
                {
                    "id": automation_id,
                    "alias": "FAIL" if fail_at == "automation" else "Automation Updated",
                },
            ),
        ]
    )
    manifest = Manifest(synced_at="t", ha_version="v", objects={})

    original_update = backend.update

    def failing_update(kind: str, identity: str, config: dict[str, Any]) -> None:
        if config.get("name") == "FAIL" or config.get("alias") == "FAIL":
            raise RuntimeError("simulated backend failure")
        original_update(kind, identity, config)

    backend.update = failing_update  # type: ignore[method-assign]

    result = apply_plan(plan, backend, manifest)

    assert result.succeeded is False
    assert backend.list_remote("input_boolean") == initial_snapshot["input_boolean"]
    assert backend.list_remote("script") == initial_snapshot["script"]
    assert backend.list_remote("automation") == initial_snapshot["automation"]


def test_manifest_updates_only_on_success() -> None:
    backend = FakeBackend()
    identity = backend.create("automation", {"id": "a1", "alias": "Original"})
    plan_time_hash = sha256_hash(backend.list_remote("automation")[identity])

    plan = Plan(
        entries=[
            _plan_entry_update(
                "automation:a1", "automation", {"id": "a1", "alias": "Local Edit"}, plan_time_hash
            )
        ]
    )
    old_manifest = Manifest(
        synced_at="OLD_TIME",
        ha_version="v",
        objects={
            "automation:a1": ManifestEntry(
                source="automations/a.py", compiled_hash=plan_time_hash, kind="dsl"
            )
        },
    )
    result = apply_plan(plan, backend, old_manifest, synced_at="NEW_TIME")

    assert result.succeeded is True
    assert result.manifest is not None
    assert result.manifest.synced_at == "NEW_TIME"
    new_hash = result.manifest.objects["automation:a1"].compiled_hash
    assert new_hash == sha256_hash(backend.list_remote("automation")[identity])


def test_manifest_unchanged_on_failure() -> None:
    backend = FakeBackend()
    identity = backend.create("automation", {"id": "a1", "alias": "Original"})
    plan_time_hash = sha256_hash(backend.list_remote("automation")[identity])

    # Drift the remote so the re-verify fails.
    backend.update("automation", identity, {"id": "a1", "alias": "Drifted"})

    plan = Plan(
        entries=[
            _plan_entry_update(
                "automation:a1", "automation", {"id": "a1", "alias": "Local Edit"}, plan_time_hash
            )
        ]
    )
    old_manifest = Manifest(
        synced_at="OLD_TIME",
        ha_version="v",
        objects={
            "automation:a1": ManifestEntry(
                source="automations/a.py", compiled_hash=plan_time_hash, kind="dsl"
            )
        },
    )
    result = apply_plan(plan, backend, old_manifest, synced_at="NEW_TIME")

    assert result.succeeded is False
    assert result.manifest is None
