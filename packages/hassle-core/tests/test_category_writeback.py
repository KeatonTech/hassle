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

**M15 work item A** (docs/ha-api-notes.md §31): §31.5a source-confirms HA's
category registry was never actually restricted to the `automation`/`script`
scopes -- ALL 13 helper kinds (9 storage-collection + 4 template config-entry)
carry categories under the shared frontend scope `"helpers"`, and `helpers`
IS now a scope `_SCOPE_FOR_KIND` maps to. Bundle PLACEMENT for helpers is
UNCHANGED this round (still the flat `helpers/misc.py`, work item B's job) --
`category_shaped_stem` still only recognizes the `automations/`/`scripts/`
trees, so a helper CREATE still takes no category action in practice (there is
no category-shaped helper file yet); `test_scope_for_kind_covers_all_13_helper_kinds`
below pins the underlying scope map directly, independent of placement.
"""

from __future__ import annotations

from typing import Any

from hassle.backend.fake import FakeBackend
from hassle.ir.keys import HELPER_DOMAINS, TEMPLATE_DOMAINS
from hassle.sync import Manifest, Plan, PlanAction, PlanEntry
from hassle.sync.apply import apply_plan
from hassle.sync.category_writeback import _SCOPE_FOR_KIND


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
    """§31.5a correction: helpers DO have a category-registry scope in real
    HA (the shared `"helpers"` scope, `_SCOPE_FOR_KIND` now maps every helper
    kind to it) -- this is no longer "helpers have no scope". But M15 work
    item A does not change bundle PLACEMENT for helpers (still the flat
    `helpers/misc.py`; work item B's job): `category_shaped_stem` only
    recognizes the `automations/`/`scripts/` trees, so a helper CREATE still
    takes no category action in practice, whatever its (hypothetical) source
    file is named -- there is no category-shaped helper file yet for it to
    match."""
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


def test_scope_for_kind_covers_all_13_helper_kinds() -> None:
    """MILESTONES M15 work item A test 1 (unit half): every one of the 13
    helper kinds (9 storage-collection + 4 template config-entry) maps to the
    shared `"helpers"` scope, not the pre-M15 `None` ("no category scope at
    all") gate -- §31.2/§31.6."""
    helper_kinds = HELPER_DOMAINS | TEMPLATE_DOMAINS
    assert len(helper_kinds) == 13
    for kind in helper_kinds:
        assert _SCOPE_FOR_KIND.get(kind) == "helpers", kind
    assert _SCOPE_FOR_KIND["automation"] == "automation"
    assert _SCOPE_FOR_KIND["script"] == "script"


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
    """M11's original claim ("no category action for ANY update") is
    superseded by M15 work item A's category-on-move sync (`test_category_move.py`)
    -- but only once there is a recorded BASE category to compare against
    (`ManifestEntry.category`, the M15 F2 amendment). This test's manifest has
    NO entry at all for `auto_hvac_1` (as if the object was never synced
    through `hassle`'s own manifest before) -- with no base to compare
    against, category-move sync conservatively takes no action, exactly the
    same "don't guess which side is right" rule M11 itself already applies
    elsewhere. `test_category_move.py` covers the case where a base IS on
    record."""
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
    # No category action for an UPDATE with no manifest-recorded base category.
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
