"""Category write-back on push-create (DESIGN §7.3/§9.2).

Pull-side placement (docs/ha-api-notes.md §22) maps an HA UI category ->
root-level `<slug(category)>.py`. Push is the reverse: when `hassle push`
CREATEs a brand-new object whose source file lives at that same `<slug>.py`
shape, Hassle assigns the matching HA category to the new object's
entity-registry entry -- first registry WRITE (every HA write goes through
the APIs the UI uses: the same `config/entity_registry/update` +
`config/category_registry/*` WS commands the UI itself uses).

Covers four required behaviors:

1. `test_push_create_assigns_matching_category_from_source_file`
2. `test_push_create_creates_missing_category_then_assigns` +
   `test_push_create_from_misc_file_takes_no_category_action`
3. `test_category_assignment_failure_does_not_fail_or_rollback_apply`
4. `test_existing_update_never_touches_categories`

All against `FakeBackend` (no network in unit tests) -- the FakeBackend
category-registry/entity-registry model, described in `hassle.backend.fake`'s
module docstring addendum.

**Category registry scopes** (docs/ha-api-notes.md §31): §31.5a
source-confirms HA's category registry was never actually restricted to the
`automation`/`script` scopes -- ALL 13 helper kinds (9 storage-collection + 4
template config-entry) carry categories under the shared frontend scope
`"helpers"`, and `helpers` IS a scope `_SCOPE_FOR_KIND` maps to.

**Bundle placement**: bundle PLACEMENT for helpers is no longer the flat
`helpers/misc.py` -- `category_shaped_stem` is root-level and kind-independent,
so a helper CREATEd at a root-level category-shaped file DOES take a
category action (`test_push_create_helper_assigns_matching_category_under_helpers_scope`),
under the shared `"helpers"` scope; `test_scope_for_kind_covers_all_13_helper_kinds`
still pins the underlying scope map directly, independent of placement.
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
                "automatic_hvac.py",
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
                "chores.py",
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
                "automatic_hvac.py",
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
                "misc.py",
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


def test_push_create_helper_assigns_matching_category_under_helpers_scope() -> None:
    """Bundle PLACEMENT for helpers uses the same root-level category-shaped
    shape as automations/scripts (`category_shaped_stem` is kind-independent
    and root-level) -- so a helper CREATEd at a category-shaped root-level
    file DOES take a category action, under the shared `"helpers"` scope
    (§31.2/§31.6), extending the scope map to real placement."""
    backend = FakeBackend()
    backend.seed_category("helpers", "cat_hvac", "HVAC")

    plan = Plan(
        entries=[
            _create_entry(
                "input_boolean:hb", "input_boolean", {"id": "hb", "name": "HB"}, "hvac.py"
            )
        ]
    )
    result = apply_plan(plan, backend, _manifest())

    assert result.succeeded is True
    assert backend.categories_for("input_boolean", "hb") == {"helpers": "cat_hvac"}


def test_push_create_helper_from_misc_file_takes_no_category_action() -> None:
    backend = FakeBackend()

    plan = Plan(
        entries=[
            _create_entry(
                "input_boolean:hb", "input_boolean", {"id": "hb", "name": "HB"}, "misc.py"
            )
        ]
    )
    result = apply_plan(plan, backend, _manifest())

    assert result.succeeded is True
    assert backend.list_categories("input_boolean") == {}
    assert backend.categories_for("input_boolean", "hb") == {}


def test_scope_for_kind_covers_all_13_helper_kinds() -> None:
    """Every one of the 13 helper kinds (9 storage-collection + 4 template
    config-entry) maps to the shared `"helpers"` scope, not the earlier
    `None` ("no category scope at all") gate -- §31.2/§31.6."""
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
                "automatic_hvac.py",
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
                "input_boolean:hb", "input_boolean", {"id": "hb", "name": "HB"}, "misc.py"
            ),
            _create_entry(
                "automation:auto_hvac_1",
                "automation",
                {"id": "auto_hvac_1", "alias": "Keep temp steady"},
                "automatic_hvac.py",
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
    """The original "no category action for ANY update" claim is superseded
    by category-on-move sync (`test_category_move.py`) -- but only once there
    is a recorded BASE category to compare against (`ManifestEntry.category`,
    a SourceWriter/plan seam amendment). This test's manifest has NO entry at
    all for `auto_hvac_1` (as if the object was never synced through
    `hassle`'s own manifest before) -- with no base to compare against,
    category-move sync conservatively takes no action, exactly the same
    "don't guess which side is right" rule applied elsewhere.
    `test_category_move.py` covers the case where a base IS on record."""
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
                "automatic_hvac.py",
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
                source_path="automatic_hvac.py",
            )
        ]
    )
    result = apply_plan(plan, backend, _manifest())

    assert result.succeeded is True
    assert backend.writes_since_reset() == 0
    assert backend.categories_for("automation", identity) == {}


# -- config/category_registry/delete -----------------------------------------


def test_delete_category_removes_row_and_clears_assignments() -> None:
    """`config/category_registry/delete` is confirmed to exist
    (docs/ha-api-notes.md §31.5c) -- it removes the category registry row AND
    strips the assignment from every entity carrying it (real HA's
    `async_clear_category_id`, §31.3)."""
    backend = FakeBackend()
    category_id = backend.create_category("automation", "Automatic HVAC")
    identity = backend.create("automation", {"id": "auto_hvac_1", "alias": "Keep temp steady"})
    backend.assign_category("automation", identity, "automation", category_id)
    assert backend.categories_for("automation", identity) == {"automation": category_id}

    backend.delete_category("automation", category_id)

    assert backend.list_categories("automation") == {}
    assert backend.categories_for("automation", identity) == {}
