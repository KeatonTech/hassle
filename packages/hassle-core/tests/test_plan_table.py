"""Table-driven plan tests — one test per row of DESIGN §8.2 (the test spec).

The table (base = manifest hash, local = freshly compiled, remote = live HA,
canonical-hashed):

| base vs remote        | base vs local | Plan action                              |
|------------------------|---------------|-------------------------------------------|
| same                   | same          | noop                                       |
| same                   | different     | update (safe)                              |
| same                   | local deleted | delete                                     |
| different (UI edit)    | same          | refresh                                    |
| different              | different     | conflict (both_edited)                     |
| different              | local deleted | conflict (deleted_locally_edited_remotely) |
| remote deleted         | same          | drop                                       |
| remote deleted         | different     | conflict (edited_locally_deleted_remotely) |
| (new local id)         | —             | create (id-collision -> conflict)          |
| (new remote id)        | —             | adopt                                      |

`compute_plan(manifest, local_objects, remote_objects)` takes local/remote as
dict[object_key, config-dict-or-None] shaped inputs (None means deleted) plus
the manifest as the merge base. Every comparison uses canonical hash equality
(`hassle.ir.canonical.sha256_hash`), per DESIGN §8.2 ("remote (canonical-hashed)").
"""

from __future__ import annotations

from hassle.ir.canonical import sha256_hash
from hassle.sync import ConflictKind, Manifest, ManifestEntry, PlanAction
from hassle.sync.plan import compute_plan

BASE_CONFIG = {"id": "a1", "alias": "Base Alias", "triggers": [], "conditions": [], "actions": []}
LOCAL_EDIT = {"id": "a1", "alias": "Local Alias", "triggers": [], "conditions": [], "actions": []}
REMOTE_EDIT = {"id": "a1", "alias": "Remote Alias", "triggers": [], "conditions": [], "actions": []}
OBJECT_KEY = "automation:a1"


def _manifest_with(object_key: str, config: dict[str, object]) -> Manifest:
    return Manifest(
        synced_at="2026-07-03T00:00:00Z",
        ha_version="2026.6.3",
        objects={
            object_key: ManifestEntry(
                source="automations/a.py",
                compiled_hash=sha256_hash(config),
                kind="dsl",
            )
        },
    )


def test_plan_noop_when_base_local_remote_all_match() -> None:
    manifest = _manifest_with(OBJECT_KEY, BASE_CONFIG)
    plan = compute_plan(
        manifest=manifest,
        local_objects={OBJECT_KEY: ("automation", BASE_CONFIG)},
        remote_objects={OBJECT_KEY: ("automation", BASE_CONFIG)},
    )
    entry = plan.entry_for(OBJECT_KEY)
    assert entry is not None
    assert entry.action is PlanAction.NOOP


def test_plan_local_edited_remote_untouched_is_update() -> None:
    # same base-vs-remote, different base-vs-local -> update (safe: remote untouched)
    manifest = _manifest_with(OBJECT_KEY, BASE_CONFIG)
    plan = compute_plan(
        manifest=manifest,
        local_objects={OBJECT_KEY: ("automation", LOCAL_EDIT)},
        remote_objects={OBJECT_KEY: ("automation", BASE_CONFIG)},
    )
    entry = plan.entry_for(OBJECT_KEY)
    assert entry is not None
    assert entry.action is PlanAction.UPDATE
    assert entry.local == LOCAL_EDIT


def test_plan_local_deleted_remote_unchanged_is_delete() -> None:
    # same base-vs-remote, local deleted -> delete
    manifest = _manifest_with(OBJECT_KEY, BASE_CONFIG)
    plan = compute_plan(
        manifest=manifest,
        local_objects={},
        remote_objects={OBJECT_KEY: ("automation", BASE_CONFIG)},
    )
    entry = plan.entry_for(OBJECT_KEY)
    assert entry is not None
    assert entry.action is PlanAction.DELETE


def test_plan_remote_edited_local_untouched_is_refresh() -> None:
    # different base-vs-remote (UI edit), same base-vs-local -> refresh
    manifest = _manifest_with(OBJECT_KEY, BASE_CONFIG)
    plan = compute_plan(
        manifest=manifest,
        local_objects={OBJECT_KEY: ("automation", BASE_CONFIG)},
        remote_objects={OBJECT_KEY: ("automation", REMOTE_EDIT)},
    )
    entry = plan.entry_for(OBJECT_KEY)
    assert entry is not None
    assert entry.action is PlanAction.REFRESH
    assert entry.remote == REMOTE_EDIT


def test_plan_both_edited_is_conflict() -> None:
    # different base-vs-remote, different base-vs-local -> conflict (both_edited)
    manifest = _manifest_with(OBJECT_KEY, BASE_CONFIG)
    plan = compute_plan(
        manifest=manifest,
        local_objects={OBJECT_KEY: ("automation", LOCAL_EDIT)},
        remote_objects={OBJECT_KEY: ("automation", REMOTE_EDIT)},
    )
    entry = plan.entry_for(OBJECT_KEY)
    assert entry is not None
    assert entry.action is PlanAction.CONFLICT
    assert entry.conflict is not None
    assert entry.conflict.kind is ConflictKind.BOTH_EDITED
    assert entry.conflict.base == BASE_CONFIG
    assert entry.conflict.local == LOCAL_EDIT
    assert entry.conflict.remote == REMOTE_EDIT


def test_plan_deleted_locally_edited_remotely_is_conflict() -> None:
    # different base-vs-remote, local deleted -> conflict (deleted locally, edited remotely)
    manifest = _manifest_with(OBJECT_KEY, BASE_CONFIG)
    plan = compute_plan(
        manifest=manifest,
        local_objects={},
        remote_objects={OBJECT_KEY: ("automation", REMOTE_EDIT)},
    )
    entry = plan.entry_for(OBJECT_KEY)
    assert entry is not None
    assert entry.action is PlanAction.CONFLICT
    assert entry.conflict is not None
    assert entry.conflict.kind is ConflictKind.DELETED_LOCALLY_EDITED_REMOTELY
    assert entry.conflict.local is None


def test_plan_remote_deleted_local_unchanged_is_drop() -> None:
    # remote deleted, base-vs-local same -> drop from bundle
    manifest = _manifest_with(OBJECT_KEY, BASE_CONFIG)
    plan = compute_plan(
        manifest=manifest,
        local_objects={OBJECT_KEY: ("automation", BASE_CONFIG)},
        remote_objects={},
    )
    entry = plan.entry_for(OBJECT_KEY)
    assert entry is not None
    assert entry.action is PlanAction.DROP


def test_plan_remote_deleted_local_edited_is_conflict() -> None:
    # remote deleted, base-vs-local different -> conflict (edited locally, deleted remotely)
    manifest = _manifest_with(OBJECT_KEY, BASE_CONFIG)
    plan = compute_plan(
        manifest=manifest,
        local_objects={OBJECT_KEY: ("automation", LOCAL_EDIT)},
        remote_objects={},
    )
    entry = plan.entry_for(OBJECT_KEY)
    assert entry is not None
    assert entry.action is PlanAction.CONFLICT
    assert entry.conflict is not None
    assert entry.conflict.kind is ConflictKind.EDITED_LOCALLY_DELETED_REMOTELY
    assert entry.conflict.remote is None


def test_plan_new_local_id_is_create() -> None:
    # object exists locally and remotely-absent, with no manifest entry -> create
    new_key = "automation:brand_new"
    new_config = {"id": "brand_new", "alias": "New"}
    manifest = Manifest(synced_at="t", ha_version="v", objects={})
    plan = compute_plan(
        manifest=manifest,
        local_objects={new_key: ("automation", new_config)},
        remote_objects={},
    )
    entry = plan.entry_for(new_key)
    assert entry is not None
    assert entry.action is PlanAction.CREATE
    assert entry.local == new_config


def test_plan_new_local_id_colliding_with_new_remote_object_is_conflict() -> None:
    # id-collision: new local id AND a new remote object under the same key -> conflict
    new_key = "automation:brand_new"
    local_config = {"id": "brand_new", "alias": "Local New"}
    remote_config = {"id": "brand_new", "alias": "Remote New"}
    manifest = Manifest(synced_at="t", ha_version="v", objects={})
    plan = compute_plan(
        manifest=manifest,
        local_objects={new_key: ("automation", local_config)},
        remote_objects={new_key: ("automation", remote_config)},
    )
    entry = plan.entry_for(new_key)
    assert entry is not None
    assert entry.action is PlanAction.CONFLICT


def test_plan_new_remote_id_is_adopt() -> None:
    # object exists remotely, absent locally, no manifest entry -> adopt on next pull
    new_key = "automation:ui_created"
    remote_config = {"id": "ui_created", "alias": "Created via UI"}
    manifest = Manifest(synced_at="t", ha_version="v", objects={})
    plan = compute_plan(
        manifest=manifest,
        local_objects={},
        remote_objects={new_key: ("automation", remote_config)},
    )
    entry = plan.entry_for(new_key)
    assert entry is not None
    assert entry.action is PlanAction.ADOPT
    assert entry.remote == remote_config


def test_first_pull_adopts_all_remote_objects() -> None:
    # Empty manifest + several remote objects, no local objects -> every one is adopt.
    manifest = Manifest(synced_at="t", ha_version="v", objects={})
    remote_objects = {
        "automation:a1": ("automation", {"id": "a1", "alias": "A"}),
        "script:s1": ("script", {"alias": "S"}),
        "input_boolean:b1": ("input_boolean", {"name": "B"}),
    }
    plan = compute_plan(manifest=manifest, local_objects={}, remote_objects=remote_objects)
    for key in remote_objects:
        entry = plan.entry_for(key)
        assert entry is not None
        assert entry.action is PlanAction.ADOPT


def test_plan_object_kind_is_recorded_on_entry() -> None:
    manifest = _manifest_with(OBJECT_KEY, BASE_CONFIG)
    plan = compute_plan(
        manifest=manifest,
        local_objects={OBJECT_KEY: ("automation", BASE_CONFIG)},
        remote_objects={OBJECT_KEY: ("automation", BASE_CONFIG)},
    )
    entry = plan.entry_for(OBJECT_KEY)
    assert entry is not None
    assert entry.kind == "automation"
