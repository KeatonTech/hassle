"""The golden fixture bundle, end to end (blueprints-design §7).

`fixtures/dsl/blueprint_managed_object/` is a bundle with ONE blueprint and
TWO instances of it. This drives it through the whole managed-object lifecycle
against `FakeBackend` — first push, re-plan, edit, delete — and pins the
ordering §4 requires at each step.

Two instances rather than one is the point: §4's rules are about a blueprint
and its instances as a *group*, and a single pair cannot distinguish a correct
implementation from one that happens to order two rows right.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from hassle.backend.fake import FakeBackend
from hassle.blueprints import instances_by_blueprint
from hassle.compiler.bundle import compile_bundle
from hassle.ir import BLUEPRINT_KIND
from hassle.sync.apply import BlueprintStillInstantiatedError, apply_plan
from hassle.sync.blueprint_drift import detect_blueprint_drift
from hassle.sync.models import Manifest, PlanAction
from hassle.sync.plan import compute_plan


def _NO_WAIT(_seconds: float) -> None:
    """A no-op settle for tests that are not about the settle itself
    (ha-api-notes §40.8). The retry only fires on a MISMATCH, so without this
    every real-drift assertion would spend the full SETTLE_TIMEOUT sleeping."""


REPO_ROOT = Path(__file__).resolve().parents[3]
BUNDLE = REPO_ROOT / "fixtures" / "dsl" / "blueprint_managed_object" / "bundle"

BLUEPRINT_KEY = "blueprint:automation/local/room-switch-controls.yaml"
IDENTITY = "automation/local/room-switch-controls.yaml"
INSTANCES = ["automation:hallway_switch_controls", "automation:office_switch_controls"]


class _Recording(FakeBackend):
    def __init__(self) -> None:
        super().__init__()
        self.log: list[tuple[str, str, str]] = []

    def create(self, kind: str, config: dict[str, Any]) -> str:
        identity = super().create(kind, config)
        self.log.append(("create", kind, identity))
        return identity

    def update(self, kind: str, identity: str, config: dict[str, Any]) -> None:
        super().update(kind, identity, config)
        self.log.append(("update", kind, identity))

    def delete(self, kind: str, identity: str) -> None:
        super().delete(kind, identity)
        self.log.append(("delete", kind, identity))


def _local_objects(bundle: Path = BUNDLE) -> dict[str, tuple[str, dict[str, Any]]]:
    result = compile_bundle(bundle)
    return {key: (obj.kind(), obj.to_ha()) for key, obj in result.objects.items()}


def _remote_objects(backend: FakeBackend) -> dict[str, tuple[str, dict[str, Any]]]:
    from hassle.ir.keys import OBJECT_KINDS

    remote: dict[str, tuple[str, dict[str, Any]]] = {}
    for kind in sorted(OBJECT_KINDS):
        for identity, config in backend.list_remote(kind).items():
            remote[f"{kind}:{identity}"] = (kind, config)
    return remote


def _empty_manifest() -> Manifest:
    return Manifest(synced_at="2026-08-10T00:00:00Z", ha_version="2026.8.0")


def _plan_and_apply(backend: _Recording, manifest: Manifest, local: dict[str, Any]):
    plan = compute_plan(
        manifest=manifest,
        local_objects=local,  # type: ignore[arg-type]
        remote_objects=_remote_objects(backend),
        blueprint_drift=detect_blueprint_drift(backend, local, sleep=_NO_WAIT),  # type: ignore[arg-type]
    )
    instances = instances_by_blueprint({key: body for key, (_k, body) in local.items()})
    result = apply_plan(plan, backend, manifest, blueprint_instances=instances)
    return plan, result


# --- the bundle itself -----------------------------------------------------


def test_the_bundle_compiles_to_one_blueprint_and_two_instances() -> None:
    local = _local_objects()
    assert set(local) == {BLUEPRINT_KEY, *INSTANCES}
    assert local[BLUEPRINT_KEY][0] == BLUEPRINT_KIND


def test_both_instances_map_to_the_one_blueprint() -> None:
    local = _local_objects()
    assert instances_by_blueprint({k: b for k, (_kind, b) in local.items()}) == {
        BLUEPRINT_KEY: INSTANCES
    }


# --- first push ------------------------------------------------------------


def test_first_push_creates_the_blueprint_before_both_instances() -> None:
    backend = _Recording()
    plan, result = _plan_and_apply(backend, _empty_manifest(), _local_objects())

    assert plan.entry_for(BLUEPRINT_KEY) is not None
    assert plan.entry_for(BLUEPRINT_KEY).action is PlanAction.CREATE  # type: ignore[union-attr]
    assert result.succeeded
    assert [(op, kind) for op, kind, _ in backend.log] == [
        ("create", BLUEPRINT_KIND),
        ("create", "automation"),
        ("create", "automation"),
    ]


def test_after_the_first_push_everything_replans_as_a_noop() -> None:
    backend = _Recording()
    local = _local_objects()
    _plan, result = _plan_and_apply(backend, _empty_manifest(), local)
    assert result.manifest is not None

    replanned = compute_plan(
        manifest=result.manifest,
        local_objects=local,  # type: ignore[arg-type]
        remote_objects=_remote_objects(backend),
        blueprint_drift=detect_blueprint_drift(backend, local, sleep=_NO_WAIT),  # type: ignore[arg-type]
    )
    assert [e.action for e in replanned.entries] == [PlanAction.NOOP] * 3


# --- editing the blueprint -------------------------------------------------


def test_editing_the_blueprint_updates_it_and_reloads(tmp_path: Path) -> None:
    backend = _Recording()
    local = _local_objects()
    _plan, first = _plan_and_apply(backend, _empty_manifest(), local)
    assert first.manifest is not None
    backend.log.clear()

    edited = _edited_bundle(tmp_path)
    plan, result = _plan_and_apply(backend, first.manifest, _local_objects(edited))

    assert plan.entry_for(BLUEPRINT_KEY).action is PlanAction.UPDATE  # type: ignore[union-attr]
    assert result.succeeded
    assert [(op, kind) for op, kind, _ in backend.log] == [("update", BLUEPRINT_KIND)]
    # §4.3: the bundle declares instances, so the blueprint save is followed
    # by an automation.reload -- the instances themselves are unchanged and so
    # would otherwise keep running the old expansion.
    assert result.blueprint_reloads == [BLUEPRINT_KEY]
    assert backend.automation_reloads == 1


def _edited_bundle(tmp_path: Path) -> Path:
    """A copy of the fixture bundle with one word changed in the blueprint."""
    import shutil

    copy = tmp_path / "bundle"
    shutil.copytree(BUNDLE, copy, ignore=shutil.ignore_patterns("__pycache__"))
    target = copy / "blueprints" / "automation" / "local" / "room-switch-controls.yaml"
    target.write_text(
        target.read_text(encoding="utf-8").replace("mode: restart", "mode: single"),
        encoding="utf-8",
    )
    return copy


# --- deleting ---------------------------------------------------------------


def test_deleting_only_the_blueprint_is_refused(tmp_path: Path) -> None:
    """§4.2: both instances are still declared, so this plan would strand
    them."""
    backend = _Recording()
    local = _local_objects()
    _plan, first = _plan_and_apply(backend, _empty_manifest(), local)
    assert first.manifest is not None
    backend.log.clear()

    without_blueprint = {k: v for k, v in local.items() if k != BLUEPRINT_KEY}
    plan = compute_plan(
        manifest=first.manifest,
        local_objects=without_blueprint,  # type: ignore[arg-type]
        remote_objects=_remote_objects(backend),
    )
    assert plan.entry_for(BLUEPRINT_KEY).action is PlanAction.DELETE  # type: ignore[union-attr]

    instances = instances_by_blueprint({k: b for k, (_kind, b) in local.items()})
    with pytest.raises(BlueprintStillInstantiatedError):
        apply_plan(plan, backend, first.manifest, blueprint_instances=instances)
    assert backend.log == []


def test_deleting_everything_removes_both_instances_first() -> None:
    backend = _Recording()
    local = _local_objects()
    _plan, first = _plan_and_apply(backend, _empty_manifest(), local)
    assert first.manifest is not None
    backend.log.clear()

    _plan, result = _plan_and_apply(backend, first.manifest, {})
    assert result.succeeded
    assert [(op, kind) for op, kind, _ in backend.log] == [
        ("delete", "automation"),
        ("delete", "automation"),
        ("delete", BLUEPRINT_KIND),
    ]
    assert backend.list_remote(BLUEPRINT_KIND) == {}


def test_deleting_everything_clears_the_manifest() -> None:
    backend = _Recording()
    local = _local_objects()
    _plan, first = _plan_and_apply(backend, _empty_manifest(), local)
    assert first.manifest is not None
    _plan2, second = _plan_and_apply(backend, first.manifest, {})
    assert second.manifest is not None
    assert second.manifest.objects == {}


# --- the drift oracle over the real bundle ---------------------------------


def test_a_remote_edit_to_the_blueprint_surfaces_as_a_conflict() -> None:
    """The oracle end to end: push, edit HA's copy behind Hassle's back
    (something a UI blueprint editor would do), re-plan."""
    backend = _Recording()
    local = _local_objects()
    _plan, first = _plan_and_apply(backend, _empty_manifest(), local)
    assert first.manifest is not None

    tampered = dict(local[BLUEPRINT_KEY][1])
    tampered["source"] = str(tampered["source"]).replace("light.turn_on", "light.toggle")
    backend.update(BLUEPRINT_KIND, IDENTITY, tampered)

    plan = compute_plan(
        manifest=first.manifest,
        local_objects=local,  # type: ignore[arg-type]
        remote_objects=_remote_objects(backend),
        blueprint_drift=detect_blueprint_drift(backend, local, sleep=_NO_WAIT),  # type: ignore[arg-type]
    )
    entry = plan.entry_for(BLUEPRINT_KEY)
    assert entry is not None
    assert entry.action is PlanAction.CONFLICT
    assert entry.message is not None and "edited in place" in entry.message


def test_the_bundles_own_blueprint_is_clean_per_the_validator() -> None:
    """§6's rules must not flag the fixture -- it is the shape the design
    prescribes."""
    from hassle.registry.blueprint_rules import validate_blueprints

    assert validate_blueprints(compile_bundle(BUNDLE)) == []
