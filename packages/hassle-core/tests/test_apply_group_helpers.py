"""Plan/apply for the config-entry group-helper domain: apply order (after
storage/template helpers, before scripts/automations), CREATE-collision
drift + rollback (§8.2 semantics unchanged), options-flow UPDATE going
through the same re-verify-before-write path as every other kind, and NOOP
short-circuit on canonical equality (fuzz coverage of the group-helper kinds).

The apply engine (`hassle.sync.apply.apply_plan`) is kind-agnostic -- these
tests prove the group-helper kinds slot into that existing machinery with
ZERO changes to the plan/apply decision logic, only the `_KIND_ORDER`
dependency-ordering tuple, mirroring `test_apply_template_helpers.py`.
"""

from __future__ import annotations

from typing import Any

import pytest

from hassle.backend.fake import FakeBackend
from hassle.ir.canonical import sha256_hash
from hassle.sync import ApplyOutcome, Manifest, Plan, PlanAction, PlanEntry
from hassle.sync.apply import apply_plan
from hassle.sync.plan import compute_plan


def _create_entry(object_key: str, kind: str, local: dict[str, Any]) -> PlanEntry:
    return PlanEntry(object_key=object_key, kind=kind, action=PlanAction.CREATE, local=local)


def test_apply_order_places_group_helpers_after_template_helpers_before_scripts() -> None:
    backend = FakeBackend()
    order: list[str] = []

    original_create = backend.create

    def tracking_create(kind: str, config: dict[str, Any]) -> str:
        order.append(kind)
        return original_create(kind, config)

    backend.create = tracking_create  # type: ignore[method-assign]

    plan = Plan(
        entries=[
            _create_entry("automation:a1", "automation", {"id": "a1", "alias": "A"}),
            _create_entry("script:s1", "script", {"alias": "S"}),
            _create_entry(
                "group_cover:top",
                "group_cover",
                {"name": "Top", "entities": ["cover.a"], "hide_members": False},
            ),
            _create_entry(
                "template_number:zones",
                "template_number",
                {
                    "name": "Zones",
                    "state": "{{ 1 }}",
                    "set_value": {"action": "input_number.set_value", "data": {}},
                },
            ),
            _create_entry("input_boolean:b1", "input_boolean", {"name": "B1"}),
        ]
    )
    manifest = Manifest(synced_at="t", ha_version="v", objects={})
    result = apply_plan(plan, backend, manifest)

    assert result.succeeded is True
    assert order == ["input_boolean", "template_number", "group_cover", "script", "automation"]


def test_group_helper_create_collision_aborts_and_rolls_back() -> None:
    backend = FakeBackend()
    manifest = Manifest(synced_at="t", ha_version="v", objects={})

    plan = Plan(
        entries=[
            _create_entry("input_boolean:hb", "input_boolean", {"id": "hb", "name": "HB"}),
            _create_entry(
                "group_cover:top",
                "group_cover",
                {"name": "Top", "entities": ["cover.a"], "hide_members": False},
            ),
        ]
    )

    # Drift: a UI-created group cover materializes under the same
    # name-derived identity before apply runs.
    backend.create("group_cover", {"name": "Top", "entities": ["cover.z"], "hide_members": True})
    backend.reset_write_tracking()

    result = apply_plan(plan, backend, manifest)

    assert result.succeeded is False
    assert result.outcomes["group_cover:top"] is ApplyOutcome.ABORTED
    assert result.outcomes["input_boolean:hb"] is ApplyOutcome.ROLLED_BACK
    assert "hb" not in backend.list_remote("input_boolean")
    assert backend.list_remote("group_cover")["top"]["entities"] == ["cover.z"]


def test_apply_populates_manifest_entry_id_for_group_helper() -> None:
    backend = FakeBackend()
    manifest = Manifest(synced_at="t", ha_version="v", objects={})
    plan = Plan(
        entries=[
            _create_entry(
                "group_cover:top",
                "group_cover",
                {"name": "Top", "entities": ["cover.a"], "hide_members": False},
            )
        ]
    )
    result = apply_plan(plan, backend, manifest, synced_at="t2")

    assert result.succeeded is True
    assert result.manifest is not None
    entry = result.manifest.objects["group_cover:top"]
    expected_entry_id = backend.entry_id_for("group_cover", "top")
    assert entry.entry_id == expected_entry_id
    assert entry.entry_id is not None


def test_group_helper_update_reverifies_hash_and_uses_options_flow() -> None:
    backend = FakeBackend()
    identity = backend.create(
        "group_cover", {"name": "Top", "entities": ["cover.a"], "hide_members": False}
    )
    entry_id_before = backend.entry_id_for("group_cover", identity)
    plan_time_hash = sha256_hash(backend.list_remote("group_cover")[identity])

    plan = Plan(
        entries=[
            PlanEntry(
                object_key="group_cover:top",
                kind="group_cover",
                action=PlanAction.UPDATE,
                local={"name": "Top", "entities": ["cover.a", "cover.b"], "hide_members": True},
                remote_hash_at_plan=plan_time_hash,
            )
        ]
    )
    manifest = Manifest(synced_at="t", ha_version="v", objects={})
    result = apply_plan(plan, backend, manifest)

    assert result.succeeded is True
    stored = backend.list_remote("group_cover")[identity]
    assert stored["entities"] == ["cover.a", "cover.b"]
    assert backend.entry_id_for("group_cover", identity) == entry_id_before


def test_group_helper_update_aborts_on_drift_since_plan() -> None:
    backend = FakeBackend()
    identity = backend.create(
        "group_cover", {"name": "Top", "entities": ["cover.a"], "hide_members": False}
    )
    plan_time_hash = sha256_hash(backend.list_remote("group_cover")[identity])

    backend.update(
        "group_cover", identity, {"name": "Top", "entities": ["cover.z"], "hide_members": False}
    )
    backend.reset_write_tracking()

    plan = Plan(
        entries=[
            PlanEntry(
                object_key="group_cover:top",
                kind="group_cover",
                action=PlanAction.UPDATE,
                local={"name": "Top", "entities": ["cover.a", "cover.b"], "hide_members": True},
                remote_hash_at_plan=plan_time_hash,
            )
        ]
    )
    manifest = Manifest(synced_at="t", ha_version="v", objects={})
    result = apply_plan(plan, backend, manifest)

    assert result.succeeded is False
    assert backend.writes_since_reset() == 0
    assert backend.list_remote("group_cover")[identity]["entities"] == ["cover.z"]


def test_group_helper_delete_reverifies_and_removes_entry() -> None:
    backend = FakeBackend()
    identity = backend.create(
        "group_cover", {"name": "Top", "entities": ["cover.a"], "hide_members": False}
    )
    plan_time_hash = sha256_hash(backend.list_remote("group_cover")[identity])

    plan = Plan(
        entries=[
            PlanEntry(
                object_key="group_cover:top",
                kind="group_cover",
                action=PlanAction.DELETE,
                remote={"name": "Top", "entities": ["cover.a"], "hide_members": False},
                remote_hash_at_plan=plan_time_hash,
            )
        ]
    )
    manifest = Manifest(synced_at="t", ha_version="v", objects={})
    result = apply_plan(plan, backend, manifest)

    assert result.succeeded is True
    assert identity not in backend.list_remote("group_cover")
    assert backend.entry_id_for("group_cover", identity) is None


def test_group_helper_plan_apply_create_then_noop_on_repush() -> None:
    backend = FakeBackend()
    manifest = Manifest(synced_at="base", ha_version="test", objects={})
    local_config = {
        "name": "Zones Plan Probe",
        "entities": ["cover.a", "cover.b"],
        "hide_members": False,
    }
    local = {"group_cover:zones_plan_probe": ("group_cover", local_config)}
    plan = compute_plan(manifest=manifest, local_objects=local, remote_objects={})
    entry = plan.entry_for("group_cover:zones_plan_probe")
    assert entry is not None and entry.action is PlanAction.CREATE

    result = apply_plan(plan, backend, manifest, synced_at="after")
    assert result.succeeded is True
    assert result.manifest is not None
    manifest_entry = result.manifest.objects["group_cover:zones_plan_probe"]
    assert manifest_entry.entry_id is not None

    remote_after = {
        f"group_cover:{identity}": ("group_cover", cfg)
        for identity, cfg in backend.list_remote("group_cover").items()
    }
    plan2 = compute_plan(manifest=result.manifest, local_objects=local, remote_objects=remote_after)
    entry2 = plan2.entry_for("group_cover:zones_plan_probe")
    assert entry2 is not None and entry2.action is PlanAction.NOOP


@pytest.mark.parametrize("fail_at", ["input_boolean", "group_cover", "script", "automation"])
def test_apply_rollback_at_each_step_including_group_helper(fail_at: str) -> None:
    backend = FakeBackend()
    helper_id = backend.create("input_boolean", {"name": "Helper Original"})
    group_id = backend.create(
        "group_cover", {"name": "Group Original", "entities": ["cover.a"], "hide_members": False}
    )
    script_id = backend.create("script", {"alias": "Script Original"})
    automation_id = backend.create("automation", {"id": "a1", "alias": "Automation Original"})

    initial_snapshot = {
        "input_boolean": dict(backend.list_remote("input_boolean")),
        "group_cover": dict(backend.list_remote("group_cover")),
        "script": dict(backend.list_remote("script")),
        "automation": dict(backend.list_remote("automation")),
    }
    entry_id_before = backend.entry_id_for("group_cover", group_id)

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
                "group_cover",
                group_id,
                {
                    "name": "Group Original",
                    "entities": ["cover.FAIL"] if fail_at == "group_cover" else ["cover.b"],
                    "hide_members": False,
                },
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
        if (
            config.get("name") == "FAIL"
            or config.get("alias") == "FAIL"
            or config.get("entities") == ["cover.FAIL"]
        ):
            raise RuntimeError("simulated backend failure")
        original_update(kind, identity, config)

    backend.update = failing_update  # type: ignore[method-assign]

    result = apply_plan(plan, backend, manifest)

    assert result.succeeded is False
    assert backend.list_remote("input_boolean") == initial_snapshot["input_boolean"]
    assert backend.list_remote("group_cover") == initial_snapshot["group_cover"]
    assert backend.list_remote("script") == initial_snapshot["script"]
    assert backend.list_remote("automation") == initial_snapshot["automation"]
    assert backend.entry_id_for("group_cover", group_id) == entry_id_before
