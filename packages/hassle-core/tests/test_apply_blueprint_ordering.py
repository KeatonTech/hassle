"""blueprints-design §4 — apply ordering for blueprints.

The one rule the field deploy taught: **HA validates an instance against the
blueprint at instance-save time.** Pushing 17 instances before their blueprint
file existed would have made HA reject every one with an opaque 400. So within
one apply:

1. blueprint `create`/`update` rows apply **before** any automation row;
2. blueprint `delete` rows apply **after** all automation rows, and validate
   refuses a plan that deletes a blueprint the bundle still instantiates;
3. after a blueprint `update`, if the bundle declares instances of it, the
   backend issues `automation.reload`;
4. rollback on a failed transactional apply respects the same ordering in
   reverse.

`blueprint` is the FIRST kind whose apply position depends on its ACTION and
not only on its kind, so this is a structural change to the sort key, not a
new entry in `_KIND_ORDER`.
"""

from __future__ import annotations

from typing import Any

import pytest

from hassle.backend.fake import FakeBackend
from hassle.blueprints import blueprint_body
from hassle.ir import BLUEPRINT_KIND, sha256_hash
from hassle.sync.apply import BlueprintStillInstantiatedError, apply_plan
from hassle.sync.models import (
    ApplyOutcome,
    Manifest,
    ManifestEntry,
    Plan,
    PlanAction,
    PlanEntry,
)

SOURCE = """\
blueprint:
  name: Room Switch Controls
  domain: automation
  input:
    switch_entity:
mode: restart
triggers:
  - trigger: state
    entity_id: !input switch_entity
actions: []
"""

PATH = "local/room-switch-controls.yaml"
BLUEPRINT_KEY = f"blueprint:automation/{PATH}"
IDENTITY = f"automation/{PATH}"

INSTANCE = {
    "id": "office_switch",
    "use_blueprint": {"path": PATH, "input": {"switch_entity": "event.office"}},
}


def _local(source: str = SOURCE) -> dict[str, Any]:
    return blueprint_body(domain="automation", path=PATH, source=source)


class _RecordingBackend(FakeBackend):
    """FakeBackend plus an ordered log of every write, so the ORDER itself is
    what the assertions are about."""

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

    def reload_automations(self) -> None:
        super().reload_automations()
        self.log.append(("reload", "automation", "*"))


def _manifest(**entries: str) -> Manifest:
    return Manifest(
        synced_at="2026-08-10T00:00:00Z",
        ha_version="2026.8.0",
        objects={
            key: ManifestEntry(source=None, compiled_hash=value, kind="blueprint")
            for key, value in entries.items()
        },
    )


def _instances(*, present: bool = True) -> dict[str, list[str]]:
    return {BLUEPRINT_KEY: ["automation:office_switch"]} if present else {}


# --- 1. blueprint writes come before automation writes ---------------------


def test_a_blueprint_create_applies_before_its_instances() -> None:
    backend = _RecordingBackend()
    plan = Plan(
        entries=[
            PlanEntry(
                object_key="automation:office_switch",
                kind="automation",
                action=PlanAction.CREATE,
                local=INSTANCE,
            ),
            PlanEntry(
                object_key=BLUEPRINT_KEY,
                kind=BLUEPRINT_KIND,
                action=PlanAction.CREATE,
                local=_local(),
            ),
        ]
    )
    result = apply_plan(plan, backend, _manifest(), blueprint_instances=_instances())
    assert result.succeeded
    assert [(op, kind) for op, kind, _ in backend.log if op != "reload"] == [
        ("create", BLUEPRINT_KIND),
        ("create", "automation"),
    ]


def test_a_blueprint_update_applies_before_automations() -> None:
    backend = _RecordingBackend()
    backend.create(BLUEPRINT_KIND, _local())
    backend.log.clear()
    edited = _local(SOURCE.replace("restart", "single"))
    plan = Plan(
        entries=[
            PlanEntry(
                object_key="automation:office_switch",
                kind="automation",
                action=PlanAction.CREATE,
                local=INSTANCE,
            ),
            PlanEntry(
                object_key=BLUEPRINT_KEY,
                kind=BLUEPRINT_KIND,
                action=PlanAction.UPDATE,
                local=edited,
                remote_hash_at_plan=backend.hash_of(BLUEPRINT_KIND, IDENTITY),
            ),
        ]
    )
    result = apply_plan(
        plan,
        backend,
        _manifest(**{BLUEPRINT_KEY: sha256_hash(_local())}),
        blueprint_instances=_instances(),
    )
    assert result.succeeded
    ops = [(op, kind) for op, kind, _ in backend.log if op != "reload"]
    assert ops.index(("update", BLUEPRINT_KIND)) < ops.index(("create", "automation"))


def test_a_blueprint_write_precedes_every_other_kind_too() -> None:
    """Not just automations: a helper an instance references is still created
    before the instance, and the blueprint before both. Ordering is a total
    order, not a pairwise exception."""
    backend = _RecordingBackend()
    plan = Plan(
        entries=[
            PlanEntry(
                object_key="automation:office_switch",
                kind="automation",
                action=PlanAction.CREATE,
                local=INSTANCE,
            ),
            PlanEntry(
                object_key="input_boolean:hold",
                kind="input_boolean",
                action=PlanAction.CREATE,
                local={"id": "hold", "name": "Hold"},
            ),
            PlanEntry(
                object_key=BLUEPRINT_KEY,
                kind=BLUEPRINT_KIND,
                action=PlanAction.CREATE,
                local=_local(),
            ),
        ]
    )
    assert apply_plan(plan, backend, _manifest(), blueprint_instances=_instances()).succeeded
    assert [kind for op, kind, _ in backend.log if op == "create"] == [
        BLUEPRINT_KIND,
        "input_boolean",
        "automation",
    ]


# --- 2. blueprint deletes come after automation deletes --------------------


def test_a_blueprint_delete_applies_after_its_instances_are_gone() -> None:
    backend = _RecordingBackend()
    backend.create(BLUEPRINT_KIND, _local())
    backend.create("automation", INSTANCE)
    backend.log.clear()
    plan = Plan(
        entries=[
            PlanEntry(
                object_key=BLUEPRINT_KEY,
                kind=BLUEPRINT_KIND,
                action=PlanAction.DELETE,
                remote_hash_at_plan=backend.hash_of(BLUEPRINT_KIND, IDENTITY),
            ),
            PlanEntry(
                object_key="automation:office_switch",
                kind="automation",
                action=PlanAction.DELETE,
                remote_hash_at_plan=backend.hash_of("automation", "office_switch"),
            ),
        ]
    )
    result = apply_plan(
        plan,
        backend,
        _manifest(**{BLUEPRINT_KEY: sha256_hash(_local())}),
        blueprint_instances=_instances(present=False),
    )
    assert result.succeeded
    assert [(op, kind) for op, kind, _ in backend.log] == [
        ("delete", "automation"),
        ("delete", BLUEPRINT_KIND),
    ]


def test_a_delete_and_a_create_in_one_plan_stay_on_opposite_sides() -> None:
    """The action-dependence made visible: two blueprint rows in one apply,
    one first and one last, with the automation row between them."""
    backend = _RecordingBackend()
    other = blueprint_body(domain="automation", path="local/old.yaml", source=SOURCE)
    backend.create(BLUEPRINT_KIND, other)
    backend.log.clear()
    plan = Plan(
        entries=[
            PlanEntry(
                object_key="blueprint:automation/local/old.yaml",
                kind=BLUEPRINT_KIND,
                action=PlanAction.DELETE,
                remote_hash_at_plan=backend.hash_of(BLUEPRINT_KIND, "automation/local/old.yaml"),
            ),
            PlanEntry(
                object_key="automation:office_switch",
                kind="automation",
                action=PlanAction.CREATE,
                local=INSTANCE,
            ),
            PlanEntry(
                object_key=BLUEPRINT_KEY,
                kind=BLUEPRINT_KIND,
                action=PlanAction.CREATE,
                local=_local(),
            ),
        ]
    )
    result = apply_plan(
        plan,
        backend,
        _manifest(**{"blueprint:automation/local/old.yaml": sha256_hash(other)}),
        blueprint_instances=_instances(),
    )
    assert result.succeeded
    assert [(op, kind) for op, kind, _ in backend.log if op != "reload"] == [
        ("create", BLUEPRINT_KIND),
        ("create", "automation"),
        ("delete", BLUEPRINT_KIND),
    ]


# --- 2b. validate refuses deleting a still-instantiated blueprint ----------


def test_deleting_a_still_instantiated_blueprint_is_refused() -> None:
    """§4.2. HA would reject every surviving instance's next save, so this is
    caught before ANY write happens rather than halfway through one."""
    backend = _RecordingBackend()
    backend.create(BLUEPRINT_KIND, _local())
    backend.log.clear()
    plan = Plan(
        entries=[
            PlanEntry(
                object_key=BLUEPRINT_KEY,
                kind=BLUEPRINT_KIND,
                action=PlanAction.DELETE,
                remote_hash_at_plan=backend.hash_of(BLUEPRINT_KIND, IDENTITY),
            ),
        ]
    )
    with pytest.raises(BlueprintStillInstantiatedError):
        apply_plan(
            plan,
            backend,
            _manifest(**{BLUEPRINT_KEY: sha256_hash(_local())}),
            blueprint_instances=_instances(),
        )


def test_the_refusal_happens_before_any_write() -> None:
    backend = _RecordingBackend()
    backend.create(BLUEPRINT_KIND, _local())
    backend.log.clear()
    plan = Plan(
        entries=[
            PlanEntry(
                object_key="input_boolean:hold",
                kind="input_boolean",
                action=PlanAction.CREATE,
                local={"id": "hold", "name": "Hold"},
            ),
            PlanEntry(
                object_key=BLUEPRINT_KEY,
                kind=BLUEPRINT_KIND,
                action=PlanAction.DELETE,
                remote_hash_at_plan=backend.hash_of(BLUEPRINT_KIND, IDENTITY),
            ),
        ]
    )
    with pytest.raises(BlueprintStillInstantiatedError):
        apply_plan(
            plan,
            backend,
            _manifest(**{BLUEPRINT_KEY: sha256_hash(_local())}),
            blueprint_instances=_instances(),
        )
    assert backend.log == []


def test_the_refusal_names_the_blueprint_the_instances_and_the_fix() -> None:
    error = BlueprintStillInstantiatedError(
        BLUEPRINT_KEY, ["automation:office_switch", "automation:kitchen_switch"]
    )
    message = str(error)
    assert PATH in message
    assert "automation:office_switch" in message
    assert "Fix:" in message


def test_deleting_a_blueprint_with_no_instances_is_allowed() -> None:
    backend = _RecordingBackend()
    backend.create(BLUEPRINT_KIND, _local())
    backend.log.clear()
    plan = Plan(
        entries=[
            PlanEntry(
                object_key=BLUEPRINT_KEY,
                kind=BLUEPRINT_KIND,
                action=PlanAction.DELETE,
                remote_hash_at_plan=backend.hash_of(BLUEPRINT_KIND, IDENTITY),
            ),
        ]
    )
    result = apply_plan(
        plan,
        backend,
        _manifest(**{BLUEPRINT_KEY: sha256_hash(_local())}),
        blueprint_instances=_instances(present=False),
    )
    assert result.succeeded


def test_no_instance_map_at_all_does_not_refuse() -> None:
    """Additive parameter: a caller that doesn't supply it (every pre-existing
    call site) behaves exactly as before."""
    backend = _RecordingBackend()
    backend.create(BLUEPRINT_KIND, _local())
    plan = Plan(
        entries=[
            PlanEntry(
                object_key=BLUEPRINT_KEY,
                kind=BLUEPRINT_KIND,
                action=PlanAction.DELETE,
                remote_hash_at_plan=backend.hash_of(BLUEPRINT_KIND, IDENTITY),
            ),
        ]
    )
    assert apply_plan(plan, backend, _manifest(**{BLUEPRINT_KEY: sha256_hash(_local())})).succeeded


# --- 3. automation.reload after a blueprint update -------------------------


def test_an_update_with_instances_reloads_automations() -> None:
    backend = _RecordingBackend()
    backend.create(BLUEPRINT_KIND, _local())
    backend.log.clear()
    plan = Plan(
        entries=[
            PlanEntry(
                object_key=BLUEPRINT_KEY,
                kind=BLUEPRINT_KIND,
                action=PlanAction.UPDATE,
                local=_local(SOURCE.replace("restart", "single")),
                remote_hash_at_plan=backend.hash_of(BLUEPRINT_KIND, IDENTITY),
            ),
        ]
    )
    result = apply_plan(
        plan,
        backend,
        _manifest(**{BLUEPRINT_KEY: sha256_hash(_local())}),
        blueprint_instances=_instances(),
    )
    assert result.succeeded
    assert backend.automation_reloads == 1
    assert result.blueprint_reloads == [BLUEPRINT_KEY]


def test_the_reload_happens_after_the_save() -> None:
    backend = _RecordingBackend()
    backend.create(BLUEPRINT_KIND, _local())
    backend.log.clear()
    plan = Plan(
        entries=[
            PlanEntry(
                object_key=BLUEPRINT_KEY,
                kind=BLUEPRINT_KIND,
                action=PlanAction.UPDATE,
                local=_local(SOURCE.replace("restart", "single")),
                remote_hash_at_plan=backend.hash_of(BLUEPRINT_KIND, IDENTITY),
            ),
        ]
    )
    apply_plan(
        plan,
        backend,
        _manifest(**{BLUEPRINT_KEY: sha256_hash(_local())}),
        blueprint_instances=_instances(),
    )
    assert [op for op, _kind, _identity in backend.log] == ["update", "reload"]


def test_an_update_with_no_instances_does_not_reload() -> None:
    """§4.3: "if the bundle declares instances of it". Nothing is live off this
    blueprint, so there is nothing to re-expand."""
    backend = _RecordingBackend()
    backend.create(BLUEPRINT_KIND, _local())
    plan = Plan(
        entries=[
            PlanEntry(
                object_key=BLUEPRINT_KEY,
                kind=BLUEPRINT_KIND,
                action=PlanAction.UPDATE,
                local=_local(SOURCE.replace("restart", "single")),
                remote_hash_at_plan=backend.hash_of(BLUEPRINT_KIND, IDENTITY),
            ),
        ]
    )
    apply_plan(
        plan,
        backend,
        _manifest(**{BLUEPRINT_KEY: sha256_hash(_local())}),
        blueprint_instances=_instances(present=False),
    )
    assert backend.automation_reloads == 0


def test_a_create_does_not_reload() -> None:
    """§4.3 says "after a blueprint `update`". A create cannot have live
    instances expanded against a file that did not exist."""
    backend = _RecordingBackend()
    plan = Plan(
        entries=[
            PlanEntry(
                object_key=BLUEPRINT_KEY,
                kind=BLUEPRINT_KIND,
                action=PlanAction.CREATE,
                local=_local(),
            ),
        ]
    )
    apply_plan(plan, backend, _manifest(), blueprint_instances=_instances())
    assert backend.automation_reloads == 0


def test_a_backend_without_reload_support_still_succeeds() -> None:
    """`reload_automations` is additive and `getattr`-probed, like
    `entry_id_for`: a Backend without it must not break the apply."""

    class _NoReload(FakeBackend):
        reload_automations = None  # type: ignore[assignment]

    backend = _NoReload()
    backend.create(BLUEPRINT_KIND, _local())
    plan = Plan(
        entries=[
            PlanEntry(
                object_key=BLUEPRINT_KEY,
                kind=BLUEPRINT_KIND,
                action=PlanAction.UPDATE,
                local=_local(SOURCE.replace("restart", "single")),
                remote_hash_at_plan=backend.hash_of(BLUEPRINT_KIND, IDENTITY),
            ),
        ]
    )
    result = apply_plan(
        plan,
        backend,
        _manifest(**{BLUEPRINT_KEY: sha256_hash(_local())}),
        blueprint_instances=_instances(),
    )
    assert result.succeeded
    assert result.blueprint_reloads == []


# --- 4. rollback respects the same ordering, reversed ----------------------


def test_rollback_undoes_in_reverse_apply_order() -> None:
    """A failure in the automation row must roll the blueprint back, and the
    restores must run in reverse: the instance first, then the blueprint it
    depends on."""

    class _FailingAutomation(_RecordingBackend):
        def create(self, kind: str, config: dict[str, Any]) -> str:
            if kind == "automation":
                raise RuntimeError("HA rejected the instance")
            return super().create(kind, config)

    backend = _FailingAutomation()
    plan = Plan(
        entries=[
            PlanEntry(
                object_key="automation:office_switch",
                kind="automation",
                action=PlanAction.CREATE,
                local=INSTANCE,
            ),
            PlanEntry(
                object_key=BLUEPRINT_KEY,
                kind=BLUEPRINT_KIND,
                action=PlanAction.CREATE,
                local=_local(),
            ),
        ]
    )
    result = apply_plan(plan, backend, _manifest(), blueprint_instances=_instances())
    assert not result.succeeded
    # The blueprint was created, then deleted back out.
    assert [(op, kind) for op, kind, _ in backend.log if op != "reload"] == [
        ("create", BLUEPRINT_KIND),
        ("delete", BLUEPRINT_KIND),
    ]
    assert backend.list_remote(BLUEPRINT_KIND) == {}


def test_a_rolled_back_blueprint_delete_reports_that_it_could_not_be_restored() -> None:
    """The limitation §2.1 forces, made loud instead of silent.

    A rollback restores from the snapshot `list_remote` gave -- and for a
    blueprint that is METADATA ONLY. The previous document exists nowhere the
    apply engine can reach: HA cannot serve it back, and the local file is
    gone (that is why the row was a delete). So this cannot be restored, and
    the honest behaviour is a purpose-built ROLLBACK_FAILED naming the file
    and the real fix -- never a sourceless save that fails with a confusing
    schema error, and never a silent success (I6).

    It is a narrow case by construction: blueprint deletes sort LAST, so
    nothing applied after one can fail and strand it; only a second blueprint
    delete failing in the same plan gets here.
    """

    class _FailingSecondDelete(_RecordingBackend):
        def delete(self, kind: str, identity: str) -> None:
            if kind == BLUEPRINT_KIND and identity.endswith("old.yaml"):
                raise RuntimeError("HA refused the second blueprint delete")
            super().delete(kind, identity)

    other = blueprint_body(domain="automation", path="local/old.yaml", source=SOURCE)
    backend = _FailingSecondDelete()
    backend.create(BLUEPRINT_KIND, _local())
    backend.create(BLUEPRINT_KIND, other)
    backend.log.clear()
    plan = Plan(
        entries=[
            PlanEntry(
                object_key=BLUEPRINT_KEY,
                kind=BLUEPRINT_KIND,
                action=PlanAction.DELETE,
                remote_hash_at_plan=backend.hash_of(BLUEPRINT_KIND, IDENTITY),
            ),
            PlanEntry(
                object_key="blueprint:automation/local/old.yaml",
                kind=BLUEPRINT_KIND,
                action=PlanAction.DELETE,
                remote_hash_at_plan=backend.hash_of(BLUEPRINT_KIND, "automation/local/old.yaml"),
            ),
        ]
    )
    result = apply_plan(
        plan,
        backend,
        _manifest(**{BLUEPRINT_KEY: sha256_hash(_local())}),
        blueprint_instances=_instances(present=False),
    )
    assert not result.succeeded
    assert result.failure_message is not None
    assert "could not be restored" in result.failure_message
    assert "from git" in result.failure_message


def test_a_rolled_back_blueprint_update_reports_the_same_limitation() -> None:
    """Same root cause, the case that can really happen: a blueprint update
    lands, then an automation row fails. The blueprint's PREVIOUS content is
    unrecoverable -- HA never had it available to read and the bundle has
    already moved on."""

    class _FailingAutomation(_RecordingBackend):
        def create(self, kind: str, config: dict[str, Any]) -> str:
            if kind == "automation":
                raise RuntimeError("HA rejected the instance")
            return super().create(kind, config)

    backend = _FailingAutomation()
    backend.create(BLUEPRINT_KIND, _local())
    backend.log.clear()
    plan = Plan(
        entries=[
            PlanEntry(
                object_key="automation:office_switch",
                kind="automation",
                action=PlanAction.CREATE,
                local=INSTANCE,
            ),
            PlanEntry(
                object_key=BLUEPRINT_KEY,
                kind=BLUEPRINT_KIND,
                action=PlanAction.UPDATE,
                local=_local(SOURCE.replace("restart", "single")),
                remote_hash_at_plan=backend.hash_of(BLUEPRINT_KIND, IDENTITY),
            ),
        ]
    )
    result = apply_plan(
        plan,
        backend,
        _manifest(**{BLUEPRINT_KEY: sha256_hash(_local())}),
        blueprint_instances=_instances(),
    )
    assert not result.succeeded
    assert result.outcomes[BLUEPRINT_KEY] is ApplyOutcome.ROLLBACK_FAILED
    assert result.failure_message is not None
    assert "overwritten" in result.failure_message


# --- manifest bookkeeping --------------------------------------------------


def test_the_manifest_records_the_local_hash_not_the_remote_metadata() -> None:
    """§3 makes the manifest's stored hash "the hash of the LOCAL file at last
    push". Recording the remote metadata hash instead would make every
    subsequent plan compare a local body against a metadata hash and report an
    endless update."""
    backend = _RecordingBackend()
    plan = Plan(
        entries=[
            PlanEntry(
                object_key=BLUEPRINT_KEY,
                kind=BLUEPRINT_KIND,
                action=PlanAction.CREATE,
                local=_local(),
                source_path=f"blueprints/automation/{PATH}",
            ),
        ]
    )
    result = apply_plan(plan, backend, _manifest(), blueprint_instances=_instances())
    assert result.manifest is not None
    assert result.manifest.objects[BLUEPRINT_KEY].compiled_hash == sha256_hash(_local())


def test_a_pushed_blueprint_plans_as_a_noop_next_time() -> None:
    """The round trip that matters: push, then re-plan with the new manifest
    and the backend's own remote view, and get nothing to do."""
    from hassle.blueprints import blueprint_metadata, blueprint_remote_body
    from hassle.sync.plan import compute_plan

    backend = _RecordingBackend()
    plan = Plan(
        entries=[
            PlanEntry(
                object_key=BLUEPRINT_KEY,
                kind=BLUEPRINT_KIND,
                action=PlanAction.CREATE,
                local=_local(),
            ),
        ]
    )
    result = apply_plan(plan, backend, _manifest(), blueprint_instances=_instances())
    assert result.manifest is not None

    replanned = compute_plan(
        manifest=result.manifest,
        local_objects={BLUEPRINT_KEY: (BLUEPRINT_KIND, _local())},
        remote_objects={
            BLUEPRINT_KEY: (
                BLUEPRINT_KIND,
                blueprint_remote_body("automation", PATH, blueprint_metadata(SOURCE)),
            )
        },
    )
    entry = replanned.entry_for(BLUEPRINT_KEY)
    assert entry is not None
    assert entry.action is PlanAction.NOOP


def test_the_manifest_kind_is_blueprint() -> None:
    """DESIGN §8.1's `kind` field already enumerates `dsl | raw | blueprint` --
    the blueprint kind is what finally uses the third value."""
    backend = _RecordingBackend()
    plan = Plan(
        entries=[
            PlanEntry(
                object_key=BLUEPRINT_KEY,
                kind=BLUEPRINT_KIND,
                action=PlanAction.CREATE,
                local=_local(),
                source_path=f"blueprints/automation/{PATH}",
            ),
        ]
    )
    result = apply_plan(plan, backend, _manifest(), blueprint_instances=_instances())
    assert result.manifest is not None
    entry = result.manifest.objects[BLUEPRINT_KEY]
    assert entry.kind == "blueprint"
    assert entry.source == f"blueprints/automation/{PATH}"
