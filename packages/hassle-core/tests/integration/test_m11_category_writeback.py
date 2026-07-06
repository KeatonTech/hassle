"""MILESTONES M11 test 1 (integration half) — category write-back on
push-create, verified end-to-end against real Home Assistant.

MILESTONES M11 test 1 explicitly says: "FakeBackend models `config/
entity_registry/update` + category registries; CI integration verifies
live." The unit suite (`test_category_writeback.py`, `test_direct_backend_
category_writeback.py`) proves the plan/apply-level logic and the exact WS
payload shapes `DirectBackend` sends; THIS suite is what actually proves those
two inferred WS commands (docs/ha-api-notes.md §30) work against real HA --
`config/category_registry/create` and `config/entity_registry/update`'s
`categories` field were never captured/verified live before this milestone,
and M10's own history (six CI rounds where source-inferred flow shapes
differed from reality, §26.0-§26.10) is exactly the risk class this suite
exists to catch early.

Covers:
1. `test_push_create_assigns_category_creating_it_first` — no pre-existing
   category: after apply, `config/category_registry/list` (scope automation)
   contains the created category, and the entity-registry entry for the new
   automation carries `categories == {"automation": <category_id>}`.
2. `test_push_create_reuses_existing_matching_category` — a pre-existing
   category whose name slugifies to the same slug is reused, never
   duplicated (category count for the scope is unchanged by the push).
3. `test_push_create_script_scope_assigns_category` — the script-scope
   variant, proving the `unique_id` lookup used by `_aassign_category` really
   does match a `script.<object_id>` entity's registry row (the coordinator's
   specific worry: does a script's entity-registry `unique_id` really equal
   its object id, the same way an automation's does?).
4. `test_push_create_preserves_other_scope_category_assignment` — I6: an
   object already carrying a category under a DIFFERENT scope keeps it after
   this scope's category is assigned (proves the client-side merge in
   `_aassign_category` isn't just a unit-test fiction). Automations/scripts
   only ever have ONE category scope apiece in real HA (`_CATEGORY_SCOPES`),
   so there is no second real scope to seed on the SAME object; this test
   instead seeds a category under the OTHER kind's scope on a second object
   and confirms assigning the first object's category doesn't disturb it --
   the closest live analogue to "a different scope's assignment survives"
   available given HA's actual category-registry scope set. See the test's
   own docstring for the full reasoning.

Every test owns its own category (globally-unique, randomized name, so
concurrent/rerun CI jobs against a persistent instance never collide) and
best-effort deletes it during teardown -- `config/category_registry/delete`
is not confirmed to exist (docs/ha-api-notes.md §30 addendum below), so
teardown is wrapped in `contextlib.suppress` and never fails the test.
"""

from __future__ import annotations

import contextlib
import uuid

import pytest

from hassle.backend import DirectBackend
from hassle.ir.keys import slugify
from hassle.sync import Plan, PlanAction, PlanEntry
from hassle.sync.apply import apply_plan
from hassle.sync.models import Manifest


def _manifest() -> Manifest:
    return Manifest(synced_at="t", ha_version="test", objects={})


def _unique_slug(prefix: str) -> str:
    """A per-test-run-unique category-name slug, so reruns against a
    persistent (non-Docker-fresh) HA instance never collide with a
    category/object left over from a previous run."""
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


@pytest.fixture
def cleanup_category(ha: DirectBackend):
    """Best-effort category cleanup for a (scope, category_id) pair -- HA's
    `config/category_registry/delete` command existence was not confirmed
    while writing this suite (docs/ha-api-notes.md §30 addendum); if it
    exists this actually deletes the category, if not this is a no-op and the
    globally-unique slug (`_unique_slug`) is what actually keeps reruns from
    colliding."""
    created: list[tuple[str, str]] = []

    def _track(scope: str, category_id: str) -> None:
        created.append((scope, category_id))

    yield _track

    for scope, category_id in created:
        with contextlib.suppress(Exception):
            ha._run(  # type: ignore[attr-defined]
                ha._client.ws_command(  # type: ignore[attr-defined]
                    "config/category_registry/delete", scope=scope, category_id=category_id
                )
            )


def test_push_create_assigns_category_creating_it_first(
    ha: DirectBackend, cleanup_category
) -> None:
    slug = _unique_slug("automatic_hvac")
    identity = f"auto_{slug}"

    before_categories = ha.list_categories("automation")
    assert slug not in {slugify(name) for name in before_categories.values()}

    plan = Plan(
        entries=[
            PlanEntry(
                object_key=f"automation:{identity}",
                kind="automation",
                action=PlanAction.CREATE,
                local={
                    "id": identity,
                    "alias": "M11 integration automation",
                    "triggers": [],
                    "conditions": [],
                    "actions": [],
                },
                source_path=f"automations/{slug}.py",
            )
        ]
    )
    result = apply_plan(plan, ha, _manifest())
    assert result.succeeded is True, result.outcomes
    assert result.category_warnings == [], result.category_warnings

    try:
        after_categories = ha.list_categories("automation")
        matches = [
            category_id for category_id, name in after_categories.items() if slugify(name) == slug
        ]
        assert len(matches) == 1, after_categories
        category_id = matches[0]
        cleanup_category("automation", category_id)

        assert ha.categories_for("automation", identity) == {"automation": category_id}
    finally:
        with contextlib.suppress(Exception):
            ha.delete("automation", identity)


def test_push_create_reuses_existing_matching_category(ha: DirectBackend, cleanup_category) -> None:
    slug = _unique_slug("plant_care")
    identity = f"auto_{slug}"

    # Pre-existing category with a name that slugifies to the same slug the
    # source path implies -- HA's category `name` field can carry the mixed
    # case/spacing a human would actually type; slugify collapses it.
    display_name = slug.replace("_", " ").title()
    category_id = ha.create_category("automation", display_name)
    cleanup_category("automation", category_id)

    before_count = len(ha.list_categories("automation"))

    plan = Plan(
        entries=[
            PlanEntry(
                object_key=f"automation:{identity}",
                kind="automation",
                action=PlanAction.CREATE,
                local={
                    "id": identity,
                    "alias": "M11 reuse-category automation",
                    "triggers": [],
                    "conditions": [],
                    "actions": [],
                },
                source_path=f"automations/{slug}.py",
            )
        ]
    )
    try:
        result = apply_plan(plan, ha, _manifest())
        assert result.succeeded is True, result.outcomes
        assert result.category_warnings == [], result.category_warnings

        after_count = len(ha.list_categories("automation"))
        assert after_count == before_count, "a matching category must be REUSED, never duplicated"
        assert ha.categories_for("automation", identity) == {"automation": category_id}
    finally:
        with contextlib.suppress(Exception):
            ha.delete("automation", identity)


def test_push_create_script_scope_assigns_category(ha: DirectBackend, cleanup_category) -> None:
    """The coordinator's specific worry: does a `script.<object_id>` entity's
    entity-registry `unique_id` actually equal the script's object id, the
    same way an automation's `unique_id` equals its config `id`
    (docs/ha-api-notes.md §2)? `DirectBackend._aassign_category` (and
    `_afetch_categories`/pull placement, §22) all assume so; this is the
    live proof for the script side specifically."""
    slug = _unique_slug("chores")
    object_id = f"script_{slug}"

    plan = Plan(
        entries=[
            PlanEntry(
                object_key=f"script:{object_id}",
                kind="script",
                action=PlanAction.CREATE,
                local={
                    "id": object_id,
                    "alias": "M11 integration script",
                    "sequence": [],
                },
                source_path=f"scripts/{slug}.py",
            )
        ]
    )
    result = apply_plan(plan, ha, _manifest())
    assert result.succeeded is True, result.outcomes
    assert result.category_warnings == [], result.category_warnings

    try:
        categories = ha.list_categories("script")
        matches = [cid for cid, name in categories.items() if slugify(name) == slug]
        assert len(matches) == 1, categories
        category_id = matches[0]
        cleanup_category("script", category_id)

        assert ha.categories_for("script", object_id) == {"script": category_id}
    finally:
        with contextlib.suppress(Exception):
            ha.delete("script", object_id)


def test_push_create_preserves_other_scope_category_assignment(
    ha: DirectBackend, cleanup_category
) -> None:
    """I6: the client-side merge in `_aassign_category` must never drop an
    existing category assignment under a scope this call isn't about.

    Real HA's category registry only has two scopes at all (`automation`,
    `script`, DESIGN §7.3/`_CATEGORY_SCOPES`) and a single object can only
    ever belong to ONE of them (an automation is never also a script) --
    so there is no way to seed a SECOND scope's category on the very same
    object under test. The closest live-verifiable analogue: create a
    SCRIPT with a script-scope category assigned first, then push-create an
    AUTOMATION whose category write-back exercises the automation scope --
    and confirm the script's own (different-scope, different-object)
    category survives untouched. This at least proves assigning one scope's
    category never corrupts another already-assigned category row it reads
    on its way past (`config/entity_registry/list` returns every entity's
    row in one call, so a client-side merge bug touching the wrong row is a
    real, catchable failure mode here even though it's a different-object
    proxy rather than a same-object one).
    """
    script_slug = _unique_slug("existing_chores")
    script_object_id = f"script_{script_slug}"
    auto_slug = _unique_slug("new_hvac")
    auto_identity = f"auto_{auto_slug}"

    # Seed: a script already carrying a script-scope category.
    script_plan = Plan(
        entries=[
            PlanEntry(
                object_key=f"script:{script_object_id}",
                kind="script",
                action=PlanAction.CREATE,
                local={"id": script_object_id, "alias": "Existing chores script", "sequence": []},
                source_path=f"scripts/{script_slug}.py",
            )
        ]
    )
    seed_result = apply_plan(script_plan, ha, _manifest())
    assert seed_result.succeeded is True, seed_result.outcomes
    script_categories = ha.list_categories("script")
    script_category_id = next(
        cid for cid, name in script_categories.items() if slugify(name) == script_slug
    )
    cleanup_category("script", script_category_id)
    assert ha.categories_for("script", script_object_id) == {"script": script_category_id}

    try:
        # Now push-create an unrelated automation whose OWN category
        # write-back exercises `config/entity_registry/list` +
        # `config/entity_registry/update` again.
        auto_plan = Plan(
            entries=[
                PlanEntry(
                    object_key=f"automation:{auto_identity}",
                    kind="automation",
                    action=PlanAction.CREATE,
                    local={
                        "id": auto_identity,
                        "alias": "New hvac automation",
                        "triggers": [],
                        "conditions": [],
                        "actions": [],
                    },
                    source_path=f"automations/{auto_slug}.py",
                )
            ]
        )
        auto_result = apply_plan(auto_plan, ha, _manifest())
        assert auto_result.succeeded is True, auto_result.outcomes
        assert auto_result.category_warnings == [], auto_result.category_warnings

        auto_categories = ha.list_categories("automation")
        auto_category_id = next(
            cid for cid, name in auto_categories.items() if slugify(name) == auto_slug
        )
        cleanup_category("automation", auto_category_id)

        # The automation got its own category ...
        assert ha.categories_for("automation", auto_identity) == {"automation": auto_category_id}
        # ... and the earlier script's category assignment is untouched.
        assert ha.categories_for("script", script_object_id) == {"script": script_category_id}
    finally:
        with contextlib.suppress(Exception):
            ha.delete("automation", auto_identity)
        with contextlib.suppress(Exception):
            ha.delete("script", script_object_id)
