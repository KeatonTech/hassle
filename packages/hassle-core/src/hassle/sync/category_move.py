"""MILESTONES M15 work item A, item 2 — category-on-move sync (three-way).

M11's `hassle.sync.category_writeback` only ever fires on a freshly-succeeded
CREATE. This module is the UPDATE-side extension: moving an EXISTING object
to a different category-shaped bundle file is now a category reassignment
on push, three-way against `ManifestEntry.category` (the base category slug
as of the last sync — the F2 amendment MILESTONES M15 authorizes).

**The rule** (MILESTONES M15 "Local moves sync back", binding):

| local vs base | remote vs base | outcome                                    |
|----------------|-----------------|--------------------------------------------|
| same           | same            | noop — nothing to sync                     |
| different      | same            | push wins: assign/unassign to match local  |
| same           | different       | pull-only: base advances to remote         |
| different      | different (values differ) | CONFLICT (I6) — never silently overwritten |

This mirrors `compute_plan`'s own base/local/remote three-way table (DESIGN
§8.2) but is evaluated independently, since an object's category is not part
of its config body (and hence not part of the hash `compute_plan` compares) —
an object can be a plain UPDATE (its config changed) while its category is
untouched, or vice versa (only its category moved, config byte-identical).

**Local category derivation is isolated behind one function**
(`local_category_for_source_path`), reusing `category_writeback`'s existing
`<tree>/<slug>.py` shape (the ONLY placement shape that exists as of M15 work
item A — work item B changes bundle layout later, at which point only this
one function needs to learn the new shape).

**I6**: like `category_writeback`, this module never raises past its own
boundary — `sync_category_on_move` always returns a result object. A
CONFLICT is reported via `.conflict_message`, never as an exception, and
`apply_plan` never advances `ManifestEntry.category` past a conflict (so the
very next plan/push surfaces the identical conflict again rather than
quietly resolving it in either direction).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hassle.ir.keys import humanize_slug
from hassle.sync.category_writeback import (
    _category_slug_from_source_path,  # pyright: ignore[reportPrivateUsage]
)

__all__ = ["CategoryMoveResult", "local_category_for_source_path", "sync_category_on_move"]


def local_category_for_source_path(kind: str, source_path: str | None) -> str | None:
    """The category-name slug `source_path` implies for `kind`, or `None` if
    uncategorized (the `misc.py` fallback, no source path at all, or a path
    that isn't category-shaped for this kind).

    The single derivation function MILESTONES M15 work item A calls for --
    delegates entirely to `category_writeback`'s existing (CREATE-side)
    predicate, since work item A does not change bundle placement at all
    (work item B's job): the EXACT same `<tree>/<slug>.py` shape that decides
    whether a freshly-CREATEd object gets a category also decides what an
    UPDATEd object's *current* local category is.
    """
    return _category_slug_from_source_path(kind, source_path)


@dataclass(frozen=True)
class CategoryMoveResult:
    """What `sync_category_on_move` did (or didn't do) for one UPDATE.

    At most one of `warning`/`conflict_message` is ever set (both `None` on a
    clean noop or a successful sync). `base_unchanged` tells the caller
    whether to advance `ManifestEntry.category`:

    - `True` -- leave the manifest's base category exactly as it was (a
      noop, a conflict, or a backend failure -- next time must
      re-attempt/re-detect the identical situation, never silently settle on
      a guess). `new_base_category` is just echoed-back `base_category` in
      this case.
    - `False` -- advance the base to `new_base_category` (a successful push
      of a local move, or a pull-only base-advance after a remote-only
      recategorization).
    """

    attempted: bool
    new_base_category: str | None
    base_unchanged: bool
    warning: str | None = None
    conflict_message: str | None = None


def sync_category_on_move(
    backend: Any,
    kind: str,
    identity: str,
    *,
    local_category: str | None,
    base_category: str | None,
    scope: str | None,
) -> CategoryMoveResult:
    """Three-way-sync `kind:identity`'s HA UI category against its bundle
    placement, for an object that already existed at plan time (an UPDATE).

    ``scope`` is `category_writeback._SCOPE_FOR_KIND.get(kind)` -- `None` for
    a kind with no category-registry scope at all (defensive; every real
    `OBJECT_KINDS` entry has one, §31.2/§31.6), in which case this is a noop.
    """
    if scope is None:
        return CategoryMoveResult(
            attempted=False, new_base_category=base_category, base_unchanged=True
        )

    categories_for = getattr(backend, "categories_for", None)
    if categories_for is None:
        # Backend doesn't support the category surface at all -- nothing to
        # sync, nothing to warn about (mirrors category_writeback's own
        # capability-probe no-op).
        return CategoryMoveResult(
            attempted=False, new_base_category=base_category, base_unchanged=True
        )

    try:
        remote_category_id = categories_for(kind, identity).get(scope)
    except Exception as exc:
        return CategoryMoveResult(
            attempted=True,
            new_base_category=base_category,
            base_unchanged=True,
            warning=(
                f"hassle push: could not read the current HA UI category for {kind}:{identity} "
                f"-- {type(exc).__name__}: {exc}. Category sync skipped this run; re-running "
                "`hassle push` will retry."
            ),
        )
    remote_category = _slug_for_category_id(backend, scope, remote_category_id)

    local_changed = local_category != base_category
    remote_changed = remote_category != base_category

    if not local_changed and not remote_changed:
        return CategoryMoveResult(
            attempted=False, new_base_category=base_category, base_unchanged=True
        )

    if local_changed and remote_changed and local_category != remote_category:
        return CategoryMoveResult(
            attempted=False,
            new_base_category=base_category,
            base_unchanged=True,
            conflict_message=(
                f"hassle push: category conflict for {kind}:{identity} -- the bundle moved it "
                f"to category {local_category or 'misc'!r} while HA's UI recategorized it to "
                f"{remote_category or 'misc'!r} (both changed since the last sync). Neither side "
                "was overwritten (I6). Fix: re-run with --accept-local/--accept-remote for this "
                "object key, or manually align one side with the other, then push again."
            ),
        )

    if not local_changed and remote_changed:
        # Pull-only: HA's UI moved it, the bundle didn't. No push action --
        # just advance the recorded base so the next plan doesn't perpetually
        # re-detect this as "remote changed".
        return CategoryMoveResult(
            attempted=False, new_base_category=remote_category, base_unchanged=False
        )

    # local_changed (and, if remote also changed, to the SAME value as
    # local -- already-converged, still fine to push/no-op idempotently):
    # push wins, assign or unassign to match the bundle's own placement.
    assign_category = getattr(backend, "assign_category", None)
    list_categories = getattr(backend, "list_categories", None)
    create_category = getattr(backend, "create_category", None)
    if assign_category is None or list_categories is None or create_category is None:
        return CategoryMoveResult(
            attempted=False, new_base_category=base_category, base_unchanged=True
        )

    try:
        if local_category is None:
            assign_category(kind, identity, scope, None)
        else:
            existing = list_categories(scope)
            category_id = _category_id_for_slug(existing, local_category)
            if category_id is None:
                category_id = create_category(scope, humanize_slug(local_category))
            assign_category(kind, identity, scope, category_id)
        return CategoryMoveResult(
            attempted=True, new_base_category=local_category, base_unchanged=False
        )
    except Exception as exc:
        return CategoryMoveResult(
            attempted=True,
            new_base_category=base_category,
            base_unchanged=True,
            warning=(
                f"hassle push: could not sync the moved category for {kind}:{identity} "
                f"-- {type(exc).__name__}: {exc}. The object's own update still applied; only "
                "its HA UI category grouping is affected. Fix: check the instance's category "
                "registry / your connection, then re-run `hassle push` to retry."
            ),
        )


def _category_id_for_slug(categories: dict[str, str], slug: str) -> str | None:
    from hassle.ir.keys import slugify

    for category_id, name in categories.items():
        if slugify(name) == slug:
            return category_id
    return None


def _slug_for_category_id(backend: Any, scope: str, category_id: str | None) -> str | None:
    if category_id is None:
        return None
    list_categories = getattr(backend, "list_categories", None)
    if list_categories is None:
        return None
    from hassle.ir.keys import slugify

    try:
        name = list_categories(scope).get(category_id)
    except Exception:
        return None
    return slugify(name) if name is not None else None
