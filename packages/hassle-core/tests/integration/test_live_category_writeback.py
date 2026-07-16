"""Category write-back on push-create, verified end-to-end against real Home
Assistant.

The unit suite (`test_category_writeback.py`, `test_direct_backend_
category_writeback.py`) proves the plan/apply-level logic and the exact WS
payload shapes `DirectBackend` sends; THIS suite is what actually proves those
two inferred WS commands (docs/ha-api-notes.md §30) work against real HA --
`config/category_registry/create` and `config/entity_registry/update`'s
`categories` field. Source-inferred flow shapes have differed from reality
before (§26.0-§26.10), and that is exactly the risk class this suite exists
to catch early.

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
   does match a `script.<object_id>` entity's registry row (does a script's
   entity-registry `unique_id` really equal its object id, the same way an
   automation's does?).
4. `test_push_create_preserves_other_scope_category_assignment` — no local or
   UI edit is silently lost: an object already carrying a category under a
   DIFFERENT scope keeps it after this scope's category is assigned (proves
   the client-side merge in `_aassign_category` isn't just a unit-test
   fiction). Automations/scripts only ever have ONE category scope apiece in
   real HA (`_CATEGORY_SCOPES`), so there is no second real scope to seed on
   the SAME object; this test instead seeds a category under the OTHER
   kind's scope on a second object and confirms assigning the first object's
   category doesn't disturb it -- the closest live analogue to "a different
   scope's assignment survives" available given HA's actual
   category-registry scope set. See the test's own docstring for the full
   reasoning.

Every test owns its own category (globally-unique, randomized name, so
concurrent/rerun CI jobs against a persistent instance never collide) and
deletes it during teardown via `DirectBackend.delete_category`
(`config/category_registry/delete`, confirmed to exist, docs/ha-api-notes.md
§31.5c).

5. `test_push_create_with_category_global_uses_exact_display_name` -- a
   push-create carrying a `category_overrides` entry for its source path
   (standing in for a bundle file's `CATEGORY = "..."` global) creates the
   category with EXACTLY that display name, live-verified via
   `config/category_registry/list`, instead of the `humanize_slug`-derived
   guess.

**Helper category scopes** (docs/ha-api-notes.md §31, source-verified --
corrects §22/§30's "helpers have no category scope" belief):

6. `test_helper_category_assign_and_readback_storage_and_template` --
   assigns a category to a storage-collection helper (`input_boolean`)
   AND a template config-entry helper (`template_number`) via
   `DirectBackend.assign_category`/`create_category` (the shared `"helpers"`
   scope, §31.2) and reads both back via `categories_for` -- live proof that
   the template-helper's `unique_id == entry_id` anchor (§31.6/§31.8) really
   does resolve to the right entity-registry row on real HA, not just in
   `FakeBackend`. (This test's first CI run caught a real bug:
   `_acreate_template_helper` was caching a flow_id instead of the real
   entry_id, §31.8.)
7. `test_same_object_two_scope_category_assignment_preserved` (§31.5d) -- the
   STRONGER "no edit silently lost" check §31.5d itself calls for: one
   automation carries a category under BOTH its own `"automation"` scope AND
   (as a synthetic second scope, proving scopes are genuinely arbitrary per
   §31.1) an unrelated `"anything_sluggy"` scope, assigned in either order --
   both survive the other's assignment on the SAME entity-registry row. This
   supersedes the cross-object proxy (test 4 above), now that a real
   same-object case is actually possible.
"""

from __future__ import annotations

import contextlib
import uuid

import pytest

from hassle.backend import DirectBackend
from hassle.compiler.template_helpers import (
    declared_template_helpers,
    reset_declared_template_helpers,
    template_number,
)
from hassle.ir.keys import slugify
from hassle.sync import Plan, PlanAction, PlanEntry
from hassle.sync.apply import apply_plan
from hassle.sync.models import Manifest

_SET_VALUE = {"action": "input_number.set_value", "data": {"value": "{{ value }}"}}


def _manifest() -> Manifest:
    return Manifest(synced_at="t", ha_version="test", objects={})


def _unique_slug(prefix: str) -> str:
    """A per-test-run-unique category-name slug, so reruns against a
    persistent (non-Docker-fresh) HA instance never collide with a
    category/object left over from a previous run."""
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


@pytest.fixture
def cleanup_category(ha: DirectBackend):
    """Category cleanup for a (scope, category_id) pair -- `config/
    category_registry/delete` is now CONFIRMED to exist (docs/ha-api-notes.md
    §31.5c, source-verified: `websocket_delete_category`), so teardown calls
    it for real via `DirectBackend.delete_category` -- no more
    `contextlib.suppress`-masked no-op (§30's addendum flagged this exact
    gap: "if CI's teardown step errors loudly ... that is itself the live
    confirmation the command doesn't exist"). The globally-unique slug
    (`_unique_slug`) is still what actually prevents cross-run collisions;
    this is best-effort cleanup, not correctness-load-bearing."""
    created: list[tuple[str, str]] = []

    def _track(scope: str, category_id: str) -> None:
        created.append((scope, category_id))

    yield _track

    for scope, category_id in created:
        ha.delete_category(scope, category_id)


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
                source_path=f"{slug}.py",
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
                source_path=f"{slug}.py",
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
    """Does a `script.<object_id>` entity's
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
                source_path=f"{slug}.py",
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
    """No local or UI edit is silently lost: the client-side merge in
    `_aassign_category` must never drop an existing category assignment
    under a scope this call isn't about.

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
                source_path=f"{script_slug}.py",
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
                    source_path=f"{auto_slug}.py",
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


def test_push_create_with_category_global_uses_exact_display_name(
    ha: DirectBackend, cleanup_category
) -> None:
    """A bundle file's `CATEGORY = "..."` global (modeled
    here as a `category_overrides` plan-apply entry, the same sidecar map
    `hassle_cli.cli`'s push path builds from the compiled bundle) supplies the
    EXACT display name for a brand-new category, live-verified via
    `config/category_registry/list` -- never the `humanize_slug` guess.

    **Deliberately punctuated `display_name`**: `slugify(display_name)` is
    NOT expected to equal `slug` here -- that's the entire point of the
    CATEGORY global (recovering an exact display name, punctuation included,
    that a slug can't hold). An earlier version of this test wrongly
    re-derived a slug from `display_name` and
    filtered `list_categories` by it, which only coincidentally matches when
    the display name happens to slugify back to the file's own slug (true for
    a tame name, false the moment punctuation collapses differently, e.g.
    "(with punctuation!)" -> `..._with_punctuation`, a different string from
    `slug`'s random suffix) -- `attempt_category_writeback` itself never
    re-slugifies the override (`hassle.sync.category_writeback`: it matches/
    creates purely by `source_path`'s slug, storing the override verbatim as
    the created row's `name`), so this test must identify "the category just
    created for this object" the same way production code does: by looking
    up `identity`'s own assignment (`categories_for`), never by re-slugifying
    the display name back apart from it.
    """
    slug = _unique_slug("automatic_hvac")
    identity = f"auto_{slug}"
    display_name = "Automatic HVAC (with punctuation!)"

    plan = Plan(
        entries=[
            PlanEntry(
                object_key=f"automation:{identity}",
                kind="automation",
                action=PlanAction.CREATE,
                local={
                    "id": identity,
                    "alias": "M12 integration automation",
                    "triggers": [],
                    "conditions": [],
                    "actions": [],
                },
                source_path=f"{slug}.py",
            )
        ]
    )
    result = apply_plan(plan, ha, _manifest(), category_overrides={f"{slug}.py": display_name})
    assert result.succeeded is True, result.outcomes
    assert result.category_warnings == [], result.category_warnings

    try:
        # Identify the category THIS object was actually assigned to --
        # never by re-slugifying `display_name` (see docstring: that is not
        # a real invariant when the override is deliberately punctuated).
        assignment = ha.categories_for("automation", identity)
        assert assignment.keys() == {"automation"}, assignment
        category_id = assignment["automation"]
        cleanup_category("automation", category_id)

        after_categories = ha.list_categories("automation")
        # The EXACT display name was used -- not humanize_slug(slug), and not
        # some derivative of it either.
        assert after_categories[category_id] == display_name
    finally:
        with contextlib.suppress(Exception):
            ha.delete("automation", identity)


# ---------------------------------------------------------------------------
# Helper category scopes
# ---------------------------------------------------------------------------


def test_helper_category_assign_and_readback_storage_and_template(
    ha: DirectBackend, cleanup_category
) -> None:
    """The shared `"helpers"` scope (docs/ha-api-notes.md §31.2)
    round-trips for BOTH a storage-collection helper (`input_boolean`,
    anchored by `unique_id == object_id`) and a template config-entry helper
    (`template_number`, anchored by `unique_id == entry_id` -- §31.6/§31.8,
    there is no CALLER-settable `unique_id` for these, but the entity's OWN
    `unique_id` equals its config entry's `entry_id`). This is also the live
    proof that `_acreate_template_helper` now caches the REAL `entry_id`
    (§31.8 fixed a bug where it cached a flow_id instead, which this exact
    test caught failing on its first CI run)."""
    slug = _unique_slug("hvac_helpers")
    category_id = ha.create_category("helpers", slug.replace("_", " ").title())
    cleanup_category("helpers", category_id)

    storage_identity = ha.create(
        "input_boolean", {"id": f"ib_{slug}", "name": f"Guest mode {slug}"}
    )

    reset_declared_template_helpers()
    template_number(
        name=f"Tank level {slug}",
        state="{{ 3 }}",
        set_value=_SET_VALUE,
        min=0,
        max=8,
        step=1,
    )
    (helper,) = declared_template_helpers()
    template_identity = ha.create("template_number", helper.to_ha())

    try:
        ha.assign_category("input_boolean", storage_identity, "helpers", category_id)
        ha.assign_category("template_number", template_identity, "helpers", category_id)

        assert ha.categories_for("input_boolean", storage_identity) == {"helpers": category_id}
        assert ha.categories_for("template_number", template_identity) == {"helpers": category_id}
    finally:
        with contextlib.suppress(Exception):
            ha.delete("input_boolean", storage_identity)
        with contextlib.suppress(Exception):
            ha.delete("template_number", template_identity)


def test_same_object_two_scope_category_assignment_preserved(
    ha: DirectBackend, cleanup_category
) -> None:
    """§31.5d: HA's category-registry `scope` is a plain, uncontrolled string
    (§31.1) -- a SINGLE entity-registry row can carry categories under
    multiple scopes at once. Assign this object's OWN `"automation"`-scope
    category, then an unrelated second scope's category on the SAME
    object -- both must survive (no local or UI edit is silently lost), each
    direction (assign order doesn't matter): this is the stronger
    same-object check §31.5d calls for, superseding the cross-object proxy
    above."""
    slug = _unique_slug("plant_care")
    identity = f"auto_{slug}"

    plan = Plan(
        entries=[
            PlanEntry(
                object_key=f"automation:{identity}",
                kind="automation",
                action=PlanAction.CREATE,
                local={
                    "id": identity,
                    "alias": "M15 two-scope automation",
                    "triggers": [],
                    "conditions": [],
                    "actions": [],
                },
                source_path=f"{slug}.py",
            )
        ]
    )
    result = apply_plan(plan, ha, _manifest())
    assert result.succeeded is True, result.outcomes
    assert result.category_warnings == [], result.category_warnings

    try:
        auto_categories = ha.list_categories("automation")
        auto_category_id = next(
            cid for cid, name in auto_categories.items() if slugify(name) == slug
        )
        cleanup_category("automation", auto_category_id)
        assert ha.categories_for("automation", identity) == {"automation": auto_category_id}

        # A second, unrelated scope's category on the SAME object.
        other_scope = "anything_sluggy"
        other_category_id = ha.create_category(other_scope, f"Other {slug}")
        cleanup_category(other_scope, other_category_id)
        ha.assign_category("automation", identity, other_scope, other_category_id)

        # Both scopes' assignments survive on the same entity-registry row.
        assert ha.categories_for("automation", identity) == {
            "automation": auto_category_id,
            other_scope: other_category_id,
        }

        # And the reverse order: re-assigning the FIRST scope again must not
        # drop the second scope either.
        ha.assign_category("automation", identity, "automation", auto_category_id)
        assert ha.categories_for("automation", identity) == {
            "automation": auto_category_id,
            other_scope: other_category_id,
        }
    finally:
        with contextlib.suppress(Exception):
            ha.delete("automation", identity)
