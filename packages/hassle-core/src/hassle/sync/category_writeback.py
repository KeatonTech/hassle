"""M11 — category write-back on push-create (MILESTONES M11, DESIGN §7.3/§9.2).

Pull-side placement (`ux/pull-organization`, docs/ha-api-notes.md §22) maps an
HA UI category onto a bundle file: ``automations/<slug(category name)>.py`` /
``scripts/<slug(category name)>.py``. This module is the reverse: when
`hassle.sync.apply.apply_plan` successfully CREATEs a brand-new automation or
script whose `PlanEntry.source_path` has that exact shape, it assigns the
matching HA category to the new object — creating the category first
(``config/category_registry/create``) if no existing category's name
slugifies to the file's stem.

**I1** (every HA write goes through the same API the UI uses): the category
registry/entity registry WS commands this drives are exactly what the HA
frontend's own category-assignment UI calls (docs/ha-api-notes.md §22, §30).

**I6** (never silently drop an edit): this module never raises past its own
boundary — `attempt_category_writeback` always returns a result object; any
backend-side failure (unsupported command, network error, anything) becomes a
warning string, never an apply failure/rollback (MILESTONES M11 test 3 — the
object itself was already created successfully by the time this runs).

**Non-goal (MILESTONES M11 test 4):** this module is only ever invoked for a
freshly-succeeded CREATE. It has no opinion about UPDATE/REFRESH/ADOPT and
`apply_plan` never calls it for those actions — existing/adopted objects'
categories are simply never touched by this code path at all.

Backend surface used (additive, NOT part of the frozen `Backend` Protocol F2 —
same `getattr`-probed pattern as `entry_id_for`/`fetch_registry_snapshot`,
docs/backend.md §3.1):

- ``list_categories(scope) -> dict[category_id, name]``
- ``create_category(scope, name) -> category_id``
- ``categories_for(kind, identity) -> dict[scope, category_id]``
- ``assign_category(kind, identity, scope, category_id) -> None``

`FakeBackend` and `DirectBackend` both implement all four (`hassle.backend.
fake`, `hassle.backend.direct`); a hand-rolled test `Backend` stub that lacks
them causes `attempt_category_writeback` to no-op silently (there is nothing
to warn about — the backend simply doesn't support categories at all, exactly
like the pre-category-registry HA guard in `DirectBackend._afetch_categories`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hassle.ir.keys import humanize_slug

# Only automations/scripts have a category-registry scope in HA (DESIGN §7.3);
# helpers keep the plain domain-default `helpers/misc.py` placement and never
# participate in category write-back.
_SCOPE_FOR_KIND = {"automation": "automation", "script": "script"}
_TREE_FOR_KIND = {"automation": "automations", "script": "scripts"}


@dataclass(frozen=True)
class CategoryWritebackResult:
    """What `attempt_category_writeback` did (or didn't do) for one CREATE."""

    attempted: bool
    warning: str | None = None


def _category_slug_from_source_path(kind: str, source_path: str | None) -> str | None:
    """The category-name slug a CREATEd object's source file implies, or
    `None` if it doesn't have the ``<tree>/<slug>.py`` shape at all (a nested
    path, the bundle root, or any name other than the expected tree) or names
    the ``misc`` fallback file (MILESTONES M11 test 2: `misc.py` -> no
    category action, exactly mirroring the pull-side placement's own
    "uncategorized -> misc.py" fallback in `bundle_ops.default_source_path`)."""
    if source_path is None:
        return None
    tree = _TREE_FOR_KIND.get(kind)
    if tree is None:
        return None
    prefix = f"{tree}/"
    if not source_path.startswith(prefix) or not source_path.endswith(".py"):
        return None
    rest = source_path[len(prefix) : -len(".py")]
    # Must be a direct child of the tree (no further "/subdir/" nesting) --
    # a deeper path is a user's own organization choice, not a category-shaped
    # placement, so it's left alone.
    if not rest or "/" in rest:
        return None
    if rest == "misc":
        return None
    return rest


def _category_id_for_slug(categories: dict[str, str], slug: str) -> str | None:
    """The category_id whose name slugifies to `slug`, or `None`."""
    from hassle.ir.keys import slugify

    for category_id, name in categories.items():
        if slugify(name) == slug:
            return category_id
    return None


def attempt_category_writeback(
    backend: Any,
    kind: str,
    identity: str,
    source_path: str | None,
    *,
    category_override: str | None = None,
) -> CategoryWritebackResult:
    """Try to assign (creating if needed) the category implied by
    `source_path` to the just-CREATEd object `kind:identity`.

    Called by `hassle.sync.apply.apply_plan` immediately after a CREATE
    succeeds — never for any other action, and never in a way that can affect
    the apply's own success/rollback bookkeeping: this function catches ALL
    exceptions internally and reports them as `.warning`, which the caller
    only ever collects into `ApplyResult.category_warnings` (MILESTONES M11
    test 3). The caller does NOT add its own try/except — the isolation
    guarantee lives entirely here.

    ``category_override`` (MILESTONES M12, additive): the exact display name
    to use if a brand-new category has to be created, in place of M11's
    `humanize_slug(slug)` guess -- sourced from a bundle file's `CATEGORY`
    module global. Callers (`hassle.sync.apply.apply_plan` /
    `hassle_cli.cli`) are responsible for only ever passing an override whose
    slug actually matches `source_path`'s stem -- this function does not
    itself re-validate that (the validator, `hassle.registry.validate`'s
    `category-slug-mismatch` Finding, is the one check for that); it only
    ever consults the override when a NEW category is actually being
    created, never when reusing an existing match (M11's "never guess which
    side is right" reuse rule is unaffected by M12 -- an existing category is
    never renamed by push regardless of what `CATEGORY` says).
    """
    scope = _SCOPE_FOR_KIND.get(kind)
    if scope is None:
        return CategoryWritebackResult(attempted=False)  # helper: no category scope in HA

    slug = _category_slug_from_source_path(kind, source_path)
    if slug is None:
        return CategoryWritebackResult(attempted=False)

    list_categories = getattr(backend, "list_categories", None)
    create_category = getattr(backend, "create_category", None)
    assign_category = getattr(backend, "assign_category", None)
    if list_categories is None or create_category is None or assign_category is None:
        # Backend doesn't support the category surface at all (e.g. a bare
        # test stub, or -- mirroring DirectBackend._afetch_categories's own
        # guard -- older HA with no category registry). Nothing to warn
        # about: there is no capability to have failed at.
        return CategoryWritebackResult(attempted=False)

    try:
        existing = list_categories(scope)
        category_id = _category_id_for_slug(existing, slug)
        if category_id is None:
            display_name = (
                category_override if category_override is not None else humanize_slug(slug)
            )
            category_id = create_category(scope, display_name)
        assign_category(kind, identity, scope, category_id)
        return CategoryWritebackResult(attempted=True)
    except Exception as exc:
        return CategoryWritebackResult(
            attempted=True,
            warning=(
                f"hassle push: could not assign category for {kind}:{identity} "
                f"(source {source_path}) -- {type(exc).__name__}: {exc}. The object itself "
                "was created successfully; only its HA UI category grouping is affected. "
                "Fix: check the instance's category registry / your connection, then re-run "
                "`hassle push` -- re-pushing an already-created object with no other changes "
                "is a safe no-op that will retry this category assignment."
            ),
        )


__all__ = ["CategoryWritebackResult", "attempt_category_writeback"]
