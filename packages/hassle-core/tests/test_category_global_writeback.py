"""M12 tests 1-3 -- `CATEGORY` module global drives the DISPLAY NAME a
push-create's category write-back uses when it has to create a brand-new HA
category (MILESTONES M12; M11's `humanize_slug` fallback stays the behavior
when no `CATEGORY` is supplied at all -- M12 test 3).

`attempt_category_writeback` gains an optional `category_override` -- the
caller (`hassle_cli.cli`/`bundle_ops`) is responsible for only ever passing an
override whose slug actually matches the source path's stem (a mismatch is
handled entirely at the call site: ignore the global, warn, matching
MILESTONES M12's "write-back additionally ignores the global with a warning
(never guesses which side is right)"). This module tests the
`attempt_category_writeback`/`apply_plan` plumbing in isolation; the CLI-level
mismatch-ignores-with-warning behavior is covered end-to-end in
`packages/hassle-cli/tests/test_push_category_global.py`.
"""

from __future__ import annotations

from hassle.backend.fake import FakeBackend
from hassle.sync import Manifest, Plan, PlanAction, PlanEntry
from hassle.sync.apply import apply_plan
from hassle.sync.category_writeback import attempt_category_writeback


def _manifest() -> Manifest:
    return Manifest(synced_at="t", ha_version="v", objects={})


# -- test 1: CATEGORY global supplies the exact created category name -------


def test_attempt_category_writeback_uses_override_display_name() -> None:
    backend = FakeBackend()
    assert backend.list_categories("automation") == {}

    result = attempt_category_writeback(
        backend,
        "automation",
        "auto_hvac_1",
        "automations/automatic_hvac.py",
        category_override="Automatic HVAC",
    )

    assert result.attempted is True
    assert result.warning is None
    categories = backend.list_categories("automation")
    assert categories == {next(iter(categories)): "Automatic HVAC"}


def test_apply_plan_threads_category_overrides_by_source_path() -> None:
    """The `apply_plan`-level plumbing: `category_overrides` is keyed by
    `PlanEntry.source_path` (never by object_key -- CATEGORY is a per-FILE
    global, DESIGN §7.3's placement being per-file too) and reaches
    `attempt_category_writeback` for the matching CREATE."""
    backend = FakeBackend()

    plan = Plan(
        entries=[
            PlanEntry(
                object_key="automation:auto_hvac_1",
                kind="automation",
                action=PlanAction.CREATE,
                local={"id": "auto_hvac_1", "alias": "Keep temp steady"},
                source_path="automations/automatic_hvac.py",
            )
        ]
    )
    result = apply_plan(
        plan,
        backend,
        _manifest(),
        category_overrides={"automations/automatic_hvac.py": "Automatic HVAC"},
    )

    assert result.succeeded is True
    assert result.category_warnings == []
    categories = backend.list_categories("automation")
    assert list(categories.values()) == ["Automatic HVAC"]


def test_apply_plan_with_no_category_overrides_keeps_m11_behavior() -> None:
    """M12 test 3: no CATEGORY global at all -> byte-identical to M11's
    `humanize_slug` fallback (no `category_overrides` argument at all, the
    default)."""
    backend = FakeBackend()

    plan = Plan(
        entries=[
            PlanEntry(
                object_key="automation:auto_hvac_1",
                kind="automation",
                action=PlanAction.CREATE,
                local={"id": "auto_hvac_1", "alias": "Keep temp steady"},
                source_path="automations/automatic_hvac.py",
            )
        ]
    )
    result = apply_plan(plan, backend, _manifest())

    assert result.succeeded is True
    categories = backend.list_categories("automation")
    assert list(categories.values()) == ["Automatic Hvac"]  # humanize_slug("automatic_hvac")


def test_apply_plan_category_overrides_missing_for_path_falls_back_to_humanize() -> None:
    """A `category_overrides` dict that simply doesn't mention this entry's
    source path (e.g. the CLI omitted a mismatched CATEGORY from the map)
    behaves exactly like "no override" for that entry -- never a KeyError."""
    backend = FakeBackend()

    plan = Plan(
        entries=[
            PlanEntry(
                object_key="automation:auto_hvac_1",
                kind="automation",
                action=PlanAction.CREATE,
                local={"id": "auto_hvac_1", "alias": "Keep temp steady"},
                source_path="automations/automatic_hvac.py",
            )
        ]
    )
    result = apply_plan(plan, backend, _manifest(), category_overrides={})

    assert result.succeeded is True
    categories = backend.list_categories("automation")
    assert list(categories.values()) == ["Automatic Hvac"]


def test_attempt_category_writeback_override_only_used_for_create_not_reuse() -> None:
    """An override is only consulted when a NEW category is created; a
    pre-existing matching category is still reused untouched (M11's own
    "never guess which side is right" reuse rule is unaffected by M12)."""
    backend = FakeBackend()
    # This name slugifies to the SAME slug the source path implies
    # ("automatic_hvac") but is spelled differently from the CATEGORY
    # override below -- proving the override is never used to rename it.
    backend.seed_category("automation", "cat_hvac", "automatic hvac")

    result = attempt_category_writeback(
        backend,
        "automation",
        "auto_hvac_1",
        "automations/automatic_hvac.py",
        category_override="Automatic HVAC",
    )

    assert result.attempted is True
    assert result.warning is None
    # Reused the existing category untouched -- the override never renames it.
    assert backend.list_categories("automation") == {"cat_hvac": "automatic hvac"}
    assert backend.categories_for("automation", "auto_hvac_1") == {"automation": "cat_hvac"}
