"""M11 — category write-back on push-create (MILESTONES M11, DESIGN §7.3/§9.2).

Pull-side placement (`ux/pull-organization`, docs/ha-api-notes.md §22) already
maps an HA UI category -> `automations/<slug(category)>.py` /
`scripts/<slug(category)>.py`. M11 is the reverse: when `hassle push` CREATEs a
brand-new automation/script whose source file lives at that same
`<tree>/<slug>.py` shape, Hassle assigns the matching HA category to the new
object's entity-registry entry -- first registry WRITE (I1: the same
`config/entity_registry/update` + `config/category_registry/*` WS commands the
UI itself uses).

Covers the milestone's four required tests:

1. `test_push_create_assigns_matching_category_from_source_file`
2. `test_push_create_creates_missing_category_then_assigns` +
   `test_push_create_from_misc_file_takes_no_category_action`
3. `test_category_assignment_failure_does_not_fail_or_rollback_apply`
4. `test_existing_update_never_touches_categories`

All against `FakeBackend` (R2: no network in unit tests) -- the FakeBackend
category-registry/entity-registry model this milestone adds, described in
`hassle.backend.fake`'s module docstring addendum.
"""

from __future__ import annotations

from typing import Any

from hassle.backend.fake import FakeBackend
from hassle.sync import Manifest, Plan, PlanAction, PlanEntry
from hassle.sync.apply import apply_plan


def _create_entry(
    object_key: str, kind: str, local: dict[str, Any], source_path: str | None
) -> PlanEntry:
    return PlanEntry(
        object_key=object_key,
        kind=kind,
        action=PlanAction.CREATE,
        local=local,
        source_path=source_path,
    )


def _update_entry(
    object_key: str, kind: str, local: dict[str, Any], plan_hash: str, source_path: str | None
) -> PlanEntry:
    return PlanEntry(
        object_key=object_key,
        kind=kind,
        action=PlanAction.UPDATE,
        local=local,
        remote_hash_at_plan=plan_hash,
        source_path=source_path,
    )


def _manifest() -> Manifest:
    return Manifest(synced_at="t", ha_version="v", objects={})


# -- test 1: matching existing category gets assigned ------------------------


def test_push_create_assigns_matching_category_from_source_file() -> None:
    backend = FakeBackend()
    backend.seed_category("automation", "cat_hvac", "Automatic HVAC")

    plan = Plan(
        entries=[
            _create_entry(
                "automation:auto_hvac_1",
                "automation",
                {"id": "auto_hvac_1", "alias": "Keep temp steady"},
                "automations/automatic_hvac.py",
            )
        ]
    )
    result = apply_plan(plan, backend, _manifest())

    assert result.succeeded is True
    assert backend.categories_for("automation", "auto_hvac_1") == {"automation": "cat_hvac"}
    assert result.category_warnings == []


def test_push_create_assigns_matching_category_for_script_scope() -> None:
    backend = FakeBackend()
    backend.seed_category("script", "cat_chores", "Chores")

    plan = Plan(
        entries=[
            _create_entry(
                "script:take_out_trash",
                "script",
                {"alias": "Take out the trash", "sequence": []},
                "scripts/chores.py",
            )
        ]
    )
    result = apply_plan(plan, backend, _manifest())

    assert result.succeeded is True
    assert backend.categories_for("script", "take_out_trash") == {"script": "cat_chores"}


# -- test 2: missing category is created first, then assigned ---------------


def test_push_create_creates_missing_category_then_assigns() -> None:
    backend = FakeBackend()
    assert backend.list_categories("automation") == {}

    plan = Plan(
        entries=[
            _create_entry(
                "automation:auto_hvac_1",
                "automation",
                {"id": "auto_hvac_1", "alias": "Keep temp steady"},
                "automations/automatic_hvac.py",
            )
        ]
    )
    result = apply_plan(plan, backend, _manifest())

    assert result.succeeded is True
    categories = backend.list_categories("automation")
    assert len(categories) == 1
    ((category_id, name),) = categories.items()
    assert name  # some human-readable name was chosen
    assert backend.categories_for("automation", "auto_hvac_1") == {"automation": category_id}


def test_push_create_from_misc_file_takes_no_category_action() -> None:
    backend = FakeBackend()

    plan = Plan(
        entries=[
            _create_entry(
                "automation:auto_misc_1",
                "automation",
                {"id": "auto_misc_1", "alias": "Whatever"},
                "automations/misc.py",
            )
        ]
    )
    result = apply_plan(plan, backend, _manifest())

    assert result.succeeded is True
    assert backend.list_categories("automation") == {}
    assert backend.categories_for("automation", "auto_misc_1") == {}


def test_push_create_with_no_source_path_takes_no_category_action() -> None:
    backend = FakeBackend()

    plan = Plan(
        entries=[
            _create_entry(
                "automation:auto_none_1", "automation", {"id": "auto_none_1", "alias": "X"}, None
            )
        ]
    )
    result = apply_plan(plan, backend, _manifest())

    assert result.succeeded is True
    assert backend.categories_for("automation", "auto_none_1") == {}


def test_push_create_helper_takes_no_category_action() -> None:
    """Helpers have no category-registry scope in HA (DESIGN §7.3) -- a
    helper CREATE never attempts category write-back, whatever its source
    file is named."""
    backend = FakeBackend()

    plan = Plan(
        entries=[
            _create_entry(
                "input_boolean:hb", "input_boolean", {"id": "hb", "name": "HB"}, "helpers/hvac.py"
            )
        ]
    )
    result = apply_plan(plan, backend, _manifest())

    assert result.succeeded is True
    assert backend.list_categories("input_boolean") == {}


# -- test 3: category assignment failure never fails or rolls back apply ----


def test_category_assignment_failure_does_not_fail_or_rollback_apply() -> None:
    backend = FakeBackend()

    def _boom(*args: object, **kwargs: object) -> str:
        raise RuntimeError("category registry unreachable")

    backend.create_category = _boom  # type: ignore[method-assign]

    plan = Plan(
        entries=[
            _create_entry(
                "automation:auto_hvac_1",
                "automation",
                {"id": "auto_hvac_1", "alias": "Keep temp steady"},
                "automations/automatic_hvac.py",
            )
        ]
    )
    result = apply_plan(plan, backend, _manifest())

    # The object itself was created successfully and apply as a whole succeeded
    # -- category assignment is metadata, never load-bearing for the object.
    assert result.succeeded is True
    assert "auto_hvac_1" in backend.list_remote("automation")
    assert len(result.category_warnings) == 1
    assert (
        "auto_hvac_1" in result.category_warnings[0]
        or "automatic_hvac" in (result.category_warnings[0])
    )


def test_category_assignment_failure_does_not_rollback_other_objects_this_run() -> None:
    backend = FakeBackend()

    def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("entity registry update rejected")

    backend.assign_category = _boom  # type: ignore[method-assign]
    backend.seed_category("automation", "cat_hvac", "Automatic HVAC")

    plan = Plan(
        entries=[
            _create_entry(
                "input_boolean:hb", "input_boolean", {"id": "hb", "name": "HB"}, "helpers/misc.py"
            ),
            _create_entry(
                "automation:auto_hvac_1",
                "automation",
                {"id": "auto_hvac_1", "alias": "Keep temp steady"},
                "automations/automatic_hvac.py",
            ),
        ]
    )
    result = apply_plan(plan, backend, _manifest())

    assert result.succeeded is True
    assert "hb" in backend.list_remote("input_boolean")
    assert "auto_hvac_1" in backend.list_remote("automation")
    assert len(result.category_warnings) == 1


# -- test 4: existing/adopted objects' categories are never retroactively touched


def test_existing_update_never_touches_categories() -> None:
    backend = FakeBackend()
    backend.seed_category("automation", "cat_hvac", "Automatic HVAC")
    identity = backend.create("automation", {"id": "auto_hvac_1", "alias": "Old alias"})
    from hassle.ir.canonical import sha256_hash

    plan_hash = sha256_hash(backend.list_remote("automation")[identity])
    backend.reset_write_tracking()

    plan = Plan(
        entries=[
            _update_entry(
                "automation:auto_hvac_1",
                "automation",
                {"id": "auto_hvac_1", "alias": "New alias"},
                plan_hash,
                "automations/automatic_hvac.py",
            )
        ]
    )
    result = apply_plan(plan, backend, _manifest())

    assert result.succeeded is True
    assert backend.list_remote("automation")[identity]["alias"] == "New alias"
    # No category action for an UPDATE, even though the source path matches
    # a category-shaped file and a matching category exists.
    assert backend.categories_for("automation", identity) == {}
    assert backend.list_categories("automation") == {"cat_hvac": "Automatic HVAC"}


def test_adopt_action_never_touches_categories() -> None:
    """ADOPT is a pull-side action (never routed through apply_plan's push
    entries at all) -- included as an explicit regression guard: apply_plan
    must not treat ADOPT as a CREATE-like action that triggers write-back."""
    backend = FakeBackend()
    identity = backend.create("automation", {"id": "auto_x", "alias": "From UI"})
    backend.reset_write_tracking()

    plan = Plan(
        entries=[
            PlanEntry(
                object_key="automation:auto_x",
                kind="automation",
                action=PlanAction.ADOPT,
                remote=backend.list_remote("automation")[identity],
                source_path="automations/automatic_hvac.py",
            )
        ]
    )
    result = apply_plan(plan, backend, _manifest())

    assert result.succeeded is True
    assert backend.writes_since_reset() == 0
    assert backend.categories_for("automation", identity) == {}
