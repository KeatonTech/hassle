"""MILESTONES M10 test 4 — plan/apply for the config-entry template-helper
domain: apply order (after storage helpers, before scripts/automations),
CREATE-collision drift + rollback (§8.2 semantics unchanged), and
options-flow UPDATE going through the same re-verify-before-write path as
every other kind.

The apply engine (`hassle.sync.apply.apply_plan`) is kind-agnostic — it calls
`Backend.create`/`update`/`delete` addressed by `(kind, identity)` exactly the
same way regardless of what kind of HA object is behind it. These tests prove
the template-helper kind slots into that existing machinery with ZERO changes
to the plan/apply decision logic, only the `_KIND_ORDER` dependency-ordering
tuple (M10 addition).

**Identity (docs/ha-api-notes.md §26.6):** there is no `unique_id` -- identity
is derived from `name` (slugified). `name` is kept CONSTANT across
create/update pairs below (an update addresses the existing identity; it
does not re-derive one), matching how the real options flow can change other
fields without recreating the entry.
"""

from __future__ import annotations

from typing import Any

import pytest

from hassle.backend.fake import FakeBackend
from hassle.ir.canonical import sha256_hash
from hassle.sync import ApplyOutcome, Manifest, Plan, PlanAction, PlanEntry
from hassle.sync.apply import apply_plan

_SET_VALUE = {"action": "input_number.set_value", "data": {"value": "{{ value }}"}}


def _create_entry(object_key: str, kind: str, local: dict[str, Any]) -> PlanEntry:
    return PlanEntry(object_key=object_key, kind=kind, action=PlanAction.CREATE, local=local)


def test_apply_order_places_template_helpers_after_storage_helpers_before_scripts() -> None:
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
                "template_number:zones",
                "template_number",
                {"name": "Zones", "state": "{{ 1 }}", "set_value": _SET_VALUE},
            ),
            _create_entry("input_boolean:b1", "input_boolean", {"name": "B"}),
        ]
    )
    manifest = Manifest(synced_at="t", ha_version="v", objects={})
    result = apply_plan(plan, backend, manifest)

    assert result.succeeded is True
    assert order == ["input_boolean", "template_number", "script", "automation"]


def test_template_helper_create_collision_aborts_and_rolls_back() -> None:
    backend = FakeBackend()
    manifest = Manifest(synced_at="t", ha_version="v", objects={})

    plan = Plan(
        entries=[
            _create_entry("input_boolean:hb", "input_boolean", {"id": "hb", "name": "HB"}),
            _create_entry(
                "template_number:zones",
                "template_number",
                {"name": "Zones", "state": "{{ 1 }}", "set_value": _SET_VALUE},
            ),
        ]
    )

    # Drift: a UI-created template number materializes under the same
    # name-derived identity before apply runs.
    backend.create(
        "template_number",
        {"name": "Zones", "state": "{{ 9 }}", "set_value": _SET_VALUE},
    )
    backend.reset_write_tracking()

    result = apply_plan(plan, backend, manifest)

    assert result.succeeded is False
    assert result.outcomes["template_number:zones"] is ApplyOutcome.ABORTED
    assert result.outcomes["input_boolean:hb"] is ApplyOutcome.ROLLED_BACK
    assert "hb" not in backend.list_remote("input_boolean")
    # The colliding template number (and its entry_id) is untouched.
    assert backend.list_remote("template_number")["zones"]["state"] == "{{ 9 }}"


def test_apply_populates_manifest_entry_id_for_template_helper() -> None:
    backend = FakeBackend()
    manifest = Manifest(synced_at="t", ha_version="v", objects={})
    plan = Plan(
        entries=[
            _create_entry(
                "template_number:zones",
                "template_number",
                {"name": "Zones", "state": "{{ 1 }}", "set_value": _SET_VALUE},
            )
        ]
    )
    result = apply_plan(plan, backend, manifest, synced_at="t2")

    assert result.succeeded is True
    assert result.manifest is not None
    entry = result.manifest.objects["template_number:zones"]
    expected_entry_id = backend.entry_id_for("template_number", "zones")
    assert entry.entry_id == expected_entry_id
    assert entry.entry_id is not None


def test_apply_manifest_entry_id_is_none_for_non_template_kinds() -> None:
    backend = FakeBackend()
    manifest = Manifest(synced_at="t", ha_version="v", objects={})
    plan = Plan(entries=[_create_entry("automation:a1", "automation", {"id": "a1", "alias": "A"})])
    result = apply_plan(plan, backend, manifest, synced_at="t2")

    assert result.succeeded is True
    assert result.manifest is not None
    assert result.manifest.objects["automation:a1"].entry_id is None


def test_template_helper_update_reverifies_hash_and_uses_options_flow() -> None:
    backend = FakeBackend()
    identity = backend.create(
        "template_number", {"name": "Zones", "state": "{{ 1 }}", "set_value": _SET_VALUE}
    )
    entry_id_before = backend.entry_id_for("template_number", identity)
    plan_time_hash = sha256_hash(backend.list_remote("template_number")[identity])

    plan = Plan(
        entries=[
            PlanEntry(
                object_key="template_number:zones",
                kind="template_number",
                action=PlanAction.UPDATE,
                local={"name": "Zones", "state": "{{ 2 }}", "set_value": _SET_VALUE},
                remote_hash_at_plan=plan_time_hash,
            )
        ]
    )
    manifest = Manifest(synced_at="t", ha_version="v", objects={})
    result = apply_plan(plan, backend, manifest)

    assert result.succeeded is True
    stored = backend.list_remote("template_number")[identity]
    assert stored["state"] == "{{ 2 }}"
    # Options-flow update: same entry_id, never a recreate (I2 analog).
    assert backend.entry_id_for("template_number", identity) == entry_id_before


def test_template_helper_update_aborts_on_drift_since_plan() -> None:
    backend = FakeBackend()
    identity = backend.create(
        "template_number", {"name": "Zones", "state": "{{ 1 }}", "set_value": _SET_VALUE}
    )
    plan_time_hash = sha256_hash(backend.list_remote("template_number")[identity])

    # Remote drifts (a UI edit) after plan, before apply.
    backend.update(
        "template_number",
        identity,
        {"name": "Zones", "state": "{{ 9 }}", "set_value": _SET_VALUE},
    )
    backend.reset_write_tracking()

    plan = Plan(
        entries=[
            PlanEntry(
                object_key="template_number:zones",
                kind="template_number",
                action=PlanAction.UPDATE,
                local={"name": "Zones", "state": "{{ 2 }}", "set_value": _SET_VALUE},
                remote_hash_at_plan=plan_time_hash,
            )
        ]
    )
    manifest = Manifest(synced_at="t", ha_version="v", objects={})
    result = apply_plan(plan, backend, manifest)

    assert result.succeeded is False
    assert backend.writes_since_reset() == 0
    assert backend.list_remote("template_number")[identity]["state"] == "{{ 9 }}"


def test_template_helper_delete_reverifies_and_removes_entry() -> None:
    backend = FakeBackend()
    identity = backend.create(
        "template_number", {"name": "Zones", "state": "{{ 1 }}", "set_value": _SET_VALUE}
    )
    plan_time_hash = sha256_hash(backend.list_remote("template_number")[identity])

    plan = Plan(
        entries=[
            PlanEntry(
                object_key="template_number:zones",
                kind="template_number",
                action=PlanAction.DELETE,
                remote={"name": "Zones", "state": "{{ 1 }}", "set_value": _SET_VALUE},
                remote_hash_at_plan=plan_time_hash,
            )
        ]
    )
    manifest = Manifest(synced_at="t", ha_version="v", objects={})
    result = apply_plan(plan, backend, manifest)

    assert result.succeeded is True
    assert identity not in backend.list_remote("template_number")
    assert backend.entry_id_for("template_number", identity) is None


@pytest.mark.parametrize("fail_at", ["input_boolean", "template_number", "script", "automation"])
def test_apply_rollback_at_each_step_including_template_helper(fail_at: str) -> None:
    backend = FakeBackend()
    helper_id = backend.create("input_boolean", {"name": "Helper Original"})
    template_id = backend.create(
        "template_number",
        {"name": "Template Original", "state": "{{ 1 }}", "set_value": _SET_VALUE},
    )
    script_id = backend.create("script", {"alias": "Script Original"})
    automation_id = backend.create("automation", {"id": "a1", "alias": "Automation Original"})

    initial_snapshot = {
        "input_boolean": dict(backend.list_remote("input_boolean")),
        "template_number": dict(backend.list_remote("template_number")),
        "script": dict(backend.list_remote("script")),
        "automation": dict(backend.list_remote("automation")),
    }
    entry_id_before = backend.entry_id_for("template_number", template_id)

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
                "template_number",
                template_id,
                {
                    "name": "Template Original",
                    "state": "FAIL" if fail_at == "template_number" else "{{ 2 }}",
                    "set_value": _SET_VALUE,
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
            or config.get("state") == "FAIL"
        ):
            raise RuntimeError("simulated backend failure")
        original_update(kind, identity, config)

    backend.update = failing_update  # type: ignore[method-assign]

    result = apply_plan(plan, backend, manifest)

    assert result.succeeded is False
    assert backend.list_remote("input_boolean") == initial_snapshot["input_boolean"]
    assert backend.list_remote("template_number") == initial_snapshot["template_number"]
    assert backend.list_remote("script") == initial_snapshot["script"]
    assert backend.list_remote("automation") == initial_snapshot["automation"]
    # entry_id survives a rollback unchanged (never recreated by rollback's
    # restore-via-update path).
    assert backend.entry_id_for("template_number", template_id) == entry_id_before
