"""Regression: a push must record base hashes such that an immediate re-plan
with zero changes is a full NOOP (owner field report, BrandtCamp bundle,
2026-07-14: an interactive push presented FALSE conflicts for seven objects
whose remote sides were byte-identical to the owner's own previous push).
False conflicts train the owner to stop reading conflict prompts, which
defeats I6 -- so "base recorded correctly by every path that writes it" gets
pinned here for the field report's kinds (automation, template_sensor).

Also pins the partial-abort path the report asked about: an interrupt
(KeyboardInterrupt, e.g. Ctrl-C or a dying SSH session) mid-apply previously
escaped `apply_plan`'s `except Exception` rollback entirely, leaving the
already-written objects live in HA with STALE manifest bases. Once the owner
edits those objects locally again, the next plan sees base != remote and
base != local -> a `both_edited` conflict against the owner's own pushed
content -- exactly the reported false-conflict signature.

(The report's cross-version hash-drift hypothesis (2) was investigated and
refuted for the PR #35 / M21 range: `storage_canonical` is byte-identical
for automations/template helpers across it, and the template-helper
`list_remote` read-back shape did not change -- only a group-only listing
path was added.)
"""

from __future__ import annotations

from typing import Any

import pytest

from hassle.backend.fake import FakeBackend
from hassle.ir.canonical import sha256_hash, storage_canonical
from hassle.ir.keys import object_key
from hassle.sync import Manifest, ManifestEntry, Plan, PlanAction
from hassle.sync.apply import apply_plan
from hassle.sync.plan import compute_plan

ObjectMap = dict[str, tuple[str, dict[str, Any]]]


def _remote_objects(backend: FakeBackend, kinds: list[str]) -> ObjectMap:
    return {
        object_key(kind, identity): (kind, config)
        for kind in kinds
        for identity, config in backend.list_remote(kind).items()
    }


def _base_entry(backend: FakeBackend, kind: str, identity: str) -> ManifestEntry:
    """A manifest entry whose base is the CURRENT remote read-back -- what a
    correct previous sync would have recorded."""
    config = backend.list_remote(kind)[identity]
    return ManifestEntry(
        source=f"{identity}.py",
        compiled_hash=sha256_hash(storage_canonical(kind, config)),
        kind="dsl",
    )


def _actions(plan: Plan) -> dict[str, PlanAction]:
    return {entry.object_key: entry.action for entry in plan.entries}


def test_push_update_then_replan_is_noop_automation() -> None:
    backend = FakeBackend()
    backend.create("automation", {"id": "hvac_coordinator", "alias": "Coordinator v1"})
    manifest = Manifest(
        synced_at="t0",
        ha_version="2026.7",
        objects={
            "automation:hvac_coordinator": _base_entry(backend, "automation", "hvac_coordinator")
        },
    )

    local: ObjectMap = {
        "automation:hvac_coordinator": (
            "automation",
            {"id": "hvac_coordinator", "alias": "Coordinator v2"},
        )
    }
    plan = compute_plan(
        manifest=manifest,
        local_objects=local,
        remote_objects=_remote_objects(backend, ["automation"]),
    )
    assert _actions(plan) == {"automation:hvac_coordinator": PlanAction.UPDATE}

    result = apply_plan(plan, backend, manifest, synced_at="t1")
    assert result.succeeded is True and result.manifest is not None

    replan = compute_plan(
        manifest=result.manifest,
        local_objects=local,
        remote_objects=_remote_objects(backend, ["automation"]),
    )
    assert _actions(replan) == {"automation:hvac_coordinator": PlanAction.NOOP}


def test_push_update_then_replan_is_noop_template_sensor() -> None:
    """The field report's config-entry helper kind: five template_sensor
    `hvac_status_*` helpers false-conflicted against the owner's own push."""
    backend = FakeBackend()
    identity = backend.create(
        "template_sensor",
        {"name": "HVAC Status Zone1", "state": "{{ states('climate.zone1') }}"},
    )
    key = object_key("template_sensor", identity)
    manifest = Manifest(
        synced_at="t0",
        ha_version="2026.7",
        objects={key: _base_entry(backend, "template_sensor", identity)},
    )

    local: ObjectMap = {
        key: (
            "template_sensor",
            {
                "name": "HVAC Status Zone1",
                "state": "{{ state_attr('climate.zone1', 'hvac_action') }}",
            },
        )
    }
    plan = compute_plan(
        manifest=manifest,
        local_objects=local,
        remote_objects=_remote_objects(backend, ["template_sensor"]),
    )
    assert _actions(plan) == {key: PlanAction.UPDATE}

    result = apply_plan(plan, backend, manifest, synced_at="t1")
    assert result.succeeded is True and result.manifest is not None

    replan = compute_plan(
        manifest=result.manifest,
        local_objects=local,
        remote_objects=_remote_objects(backend, ["template_sensor"]),
    )
    assert _actions(replan) == {key: PlanAction.NOOP}


def test_push_create_then_replan_is_noop() -> None:
    backend = FakeBackend()
    local: ObjectMap = {
        "automation:daily_reset": (
            "automation",
            {"id": "daily_reset", "alias": "Automatic Daily Reset"},
        )
    }
    manifest = Manifest(synced_at="t0", ha_version="2026.7", objects={})

    plan = compute_plan(
        manifest=manifest,
        local_objects=local,
        remote_objects=_remote_objects(backend, ["automation"]),
    )
    assert _actions(plan) == {"automation:daily_reset": PlanAction.CREATE}

    result = apply_plan(plan, backend, manifest, synced_at="t1")
    assert result.succeeded is True and result.manifest is not None

    replan = compute_plan(
        manifest=result.manifest,
        local_objects=local,
        remote_objects=_remote_objects(backend, ["automation"]),
    )
    assert _actions(replan) == {"automation:daily_reset": PlanAction.NOOP}


def test_interrupt_mid_apply_rolls_back_so_replan_never_false_conflicts() -> None:
    """A KeyboardInterrupt mid-apply must roll back what was already written
    (then re-raise). Without the rollback, the interrupted push leaves the
    already-written objects live with stale manifest bases; a later local
    edit then re-plans them as `both_edited` conflicts against the owner's
    OWN pushed content (field report: FALSE conflicts, no UI edit existed)."""
    backend = FakeBackend()
    backend.create("automation", {"id": "a1", "alias": "one v1"})
    backend.create("automation", {"id": "a2", "alias": "two v1"})
    manifest = Manifest(
        synced_at="t0",
        ha_version="2026.7",
        objects={
            "automation:a1": _base_entry(backend, "automation", "a1"),
            "automation:a2": _base_entry(backend, "automation", "a2"),
        },
    )

    local_v2: ObjectMap = {
        "automation:a1": ("automation", {"id": "a1", "alias": "one v2"}),
        "automation:a2": ("automation", {"id": "a2", "alias": "two v2"}),
    }
    plan = compute_plan(
        manifest=manifest,
        local_objects=local_v2,
        remote_objects=_remote_objects(backend, ["automation"]),
    )
    assert set(_actions(plan).values()) == {PlanAction.UPDATE}

    original_update = backend.update

    def interrupting_update(kind: str, identity: str, config: dict[str, Any]) -> None:
        if identity == "a2":
            raise KeyboardInterrupt
        original_update(kind, identity, config)

    backend.update = interrupting_update  # type: ignore[method-assign]
    with pytest.raises(KeyboardInterrupt):
        apply_plan(plan, backend, manifest, synced_at="t1")
    backend.update = original_update  # type: ignore[method-assign]

    # a1 (written before the interrupt) was rolled back: HA state == pre-apply.
    assert backend.list_remote("automation")["a1"]["alias"] == "one v1"
    assert backend.list_remote("automation")["a2"]["alias"] == "two v1"

    # The owner keeps working: edits both objects locally, plans again. The
    # old manifest (never advanced -- the push didn't complete) still agrees
    # with the rolled-back remote, so this is a plain UPDATE, never a conflict.
    local_v3: ObjectMap = {
        "automation:a1": ("automation", {"id": "a1", "alias": "one v3"}),
        "automation:a2": ("automation", {"id": "a2", "alias": "two v3"}),
    }
    replan = compute_plan(
        manifest=manifest,
        local_objects=local_v3,
        remote_objects=_remote_objects(backend, ["automation"]),
    )
    assert _actions(replan) == {
        "automation:a1": PlanAction.UPDATE,
        "automation:a2": PlanAction.UPDATE,
    }
