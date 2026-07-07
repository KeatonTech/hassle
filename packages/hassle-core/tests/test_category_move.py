"""MILESTONES M15 work item A, item 2 -- category-on-move sync.

M11 write-back only ever fires on CREATE. This module (`hassle.sync.
category_move`) extends the same mechanism to UPDATE: moving an EXISTING
object to a different category-shaped file is now a category reassignment
on push, three-way against `ManifestEntry.category` (the F2 amendment MILESTONES
M15 §"Local moves sync back" authorizes -- "base category slug at last sync").

The rule (exactly the MILESTONES binding-semantics paragraph):

- local category == base, remote category == base -> noop (nothing to sync).
- local category != base, remote category == base -> push wins: assign/unassign
  the object's category to match local (the user moved the file; HA hadn't
  changed) -- extends M11's create-only write-back to updates.
- local category == base, remote category != base -> pull-only: the base
  advances to the new remote category (recorded in the next manifest), no
  push action at all (the object didn't move locally; HA's UI recategorized it).
- local category != base AND remote category != base, to DIFFERENT values ->
  CONFLICT (I6): never silently overwritten in either direction.

Covers (this file's test names):

1. `test_move_between_category_files_pushes_new_category` -- local move,
   remote unchanged -> category reassigned on push.
2. `test_move_to_misc_unassigns_category` -- local move to the `misc.py`
   fallback -> category is UNASSIGNED (the M11-established `{scope: None}`
   unset primitive, §31.5b).
3. `test_remote_only_recategorization_is_pull_only_no_push_action` -- remote
   changed, local didn't -> no push-side category action at all (this is a
   pull-side concern, base simply advances in the next manifest).
4. `test_conflicting_move_and_remote_recategorization_is_a_conflict` -- both
   sides changed to DIFFERENT values -> surfaced as a conflict, neither side
   silently wins.
5. `test_noop_when_local_and_remote_both_match_base` -- nothing changed on
   either side -> no category action, no conflict.

All against `FakeBackend` (R2: no network in unit tests), at the `apply_plan`
level -- the same test shape `test_category_writeback.py` (M11) uses.

Source paths below use the MILESTONES M15 work item B root-level shape
(`"automatic_hvac.py"`, not the work-item-A-era `"automations/automatic_hvac.py"`)
-- `local_category_for_source_path` delegates entirely to `category_shaped_stem`,
so this file's actual logic under test (the three-way category-move rule) is
unaffected by which shape the paths use; only the literal strings changed.
"""

from __future__ import annotations

from typing import Any

from hassle.backend.fake import FakeBackend
from hassle.ir.canonical import sha256_hash
from hassle.sync import Manifest, ManifestEntry, Plan, PlanAction, PlanEntry
from hassle.sync.apply import apply_plan


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


def _manifest_with_category(
    object_key: str, compiled_hash: str, category: str | None, source: str | None = None
) -> Manifest:
    return Manifest(
        synced_at="t",
        ha_version="v",
        objects={
            object_key: ManifestEntry(source=source, compiled_hash=compiled_hash, category=category)
        },
    )


def _seed_automation(backend: FakeBackend, identity: str, alias: str) -> str:
    return backend.create("automation", {"id": identity, "alias": alias})


# -- test 1: local move between two category-shaped files -------------------


def test_move_between_category_files_pushes_new_category() -> None:
    backend = FakeBackend()
    backend.seed_category("automation", "cat_hvac", "Automatic HVAC")
    backend.seed_category("automation", "cat_lighting", "Lighting")
    identity = _seed_automation(backend, "auto_1", "Keep temp steady")
    backend.assign_category("automation", identity, "automation", "cat_hvac")
    plan_hash = sha256_hash(backend.list_remote("automation")[identity])
    backend.reset_write_tracking()

    manifest = _manifest_with_category(
        "automation:auto_1", plan_hash, "automatic_hvac", "automatic_hvac.py"
    )
    plan = Plan(
        entries=[
            _update_entry(
                "automation:auto_1",
                "automation",
                {"id": "auto_1", "alias": "Keep temp steady"},
                plan_hash,
                "lighting.py",  # moved to a different category file
            )
        ]
    )
    result = apply_plan(plan, backend, manifest)

    assert result.succeeded is True
    assert result.category_conflicts == []
    assert backend.categories_for("automation", identity) == {"automation": "cat_lighting"}
    new_entry = result.manifest.objects["automation:auto_1"]  # type: ignore[union-attr]
    assert new_entry.category == "lighting"


# -- test 2: local move to misc.py unassigns the category --------------------


def test_move_to_misc_unassigns_category() -> None:
    backend = FakeBackend()
    backend.seed_category("automation", "cat_hvac", "Automatic HVAC")
    identity = _seed_automation(backend, "auto_1", "Keep temp steady")
    backend.assign_category("automation", identity, "automation", "cat_hvac")
    plan_hash = sha256_hash(backend.list_remote("automation")[identity])
    backend.reset_write_tracking()

    manifest = _manifest_with_category(
        "automation:auto_1", plan_hash, "automatic_hvac", "automatic_hvac.py"
    )
    plan = Plan(
        entries=[
            _update_entry(
                "automation:auto_1",
                "automation",
                {"id": "auto_1", "alias": "Keep temp steady"},
                plan_hash,
                "misc.py",
            )
        ]
    )
    result = apply_plan(plan, backend, manifest)

    assert result.succeeded is True
    assert result.category_conflicts == []
    # Real HA's per-scope unset REMOVES the scope key entirely (§31.3) --
    # never a lingering `{"automation": None}` entry.
    assert backend.categories_for("automation", identity) == {}
    new_entry = result.manifest.objects["automation:auto_1"]  # type: ignore[union-attr]
    assert new_entry.category is None


# -- test 3: remote-only recategorization is pull-only, no push action ------


def test_remote_only_recategorization_is_pull_only_no_push_action() -> None:
    backend = FakeBackend()
    backend.seed_category("automation", "cat_hvac", "Automatic HVAC")
    backend.seed_category("automation", "cat_lighting", "Lighting")
    identity = _seed_automation(backend, "auto_1", "Keep temp steady")
    # HA-side (UI) recategorization since base -- nothing pushed this changed it.
    backend.assign_category("automation", identity, "automation", "cat_lighting")
    plan_hash = sha256_hash(backend.list_remote("automation")[identity])
    backend.reset_write_tracking()

    manifest = _manifest_with_category(
        "automation:auto_1", plan_hash, "automatic_hvac", "automatic_hvac.py"
    )
    plan = Plan(
        entries=[
            _update_entry(
                "automation:auto_1",
                "automation",
                {"id": "auto_1", "alias": "Keep temp steady"},
                plan_hash,
                # Local source path UNCHANGED from base -- the object didn't move.
                "automatic_hvac.py",
            )
        ]
    )
    result = apply_plan(plan, backend, manifest)

    assert result.succeeded is True
    assert result.category_conflicts == []
    # No push-side category action: the remote's "lighting" assignment survives
    # untouched (never clobbered back to "automatic_hvac").
    assert backend.categories_for("automation", identity) == {"automation": "cat_lighting"}
    # The manifest's base advances to reflect the new remote reality, so the
    # NEXT plan doesn't perpetually re-detect this as "remote changed".
    new_entry = result.manifest.objects["automation:auto_1"]  # type: ignore[union-attr]
    assert new_entry.category == "lighting"


# -- test 4: conflicting move -------------------------------------------------


def test_conflicting_move_and_remote_recategorization_is_a_conflict() -> None:
    backend = FakeBackend()
    backend.seed_category("automation", "cat_hvac", "Automatic HVAC")
    backend.seed_category("automation", "cat_lighting", "Lighting")
    backend.seed_category("automation", "cat_security", "Security")
    identity = _seed_automation(backend, "auto_1", "Keep temp steady")
    # Remote (HA UI) moved it to "lighting" since base ...
    backend.assign_category("automation", identity, "automation", "cat_lighting")
    plan_hash = sha256_hash(backend.list_remote("automation")[identity])
    backend.reset_write_tracking()

    manifest = _manifest_with_category(
        "automation:auto_1", plan_hash, "automatic_hvac", "automatic_hvac.py"
    )
    plan = Plan(
        entries=[
            _update_entry(
                "automation:auto_1",
                "automation",
                {"id": "auto_1", "alias": "Keep temp steady"},
                plan_hash,
                # ... but the LOCAL bundle moved it to a DIFFERENT category, "security".
                "security.py",
            )
        ]
    )
    result = apply_plan(plan, backend, manifest)

    assert result.succeeded is True  # the object's own content update still applies (I6:
    # a category conflict is metadata-only, never blocks/rolls back the object itself)
    assert len(result.category_conflicts) == 1
    assert "auto_1" in result.category_conflicts[0]
    # Neither side was silently overwritten: remote still shows what HA had
    # (never force-reset to local's "security"), and the manifest's base
    # category is UNCHANGED (not advanced to either side) so the very next
    # plan/push surfaces this same conflict again rather than silently
    # resolving it.
    assert backend.categories_for("automation", identity) == {"automation": "cat_lighting"}
    new_entry = result.manifest.objects["automation:auto_1"]  # type: ignore[union-attr]
    assert new_entry.category == "automatic_hvac"


# -- test 5: both sides match base -> noop -----------------------------------


def test_noop_when_local_and_remote_both_match_base() -> None:
    backend = FakeBackend()
    backend.seed_category("automation", "cat_hvac", "Automatic HVAC")
    identity = _seed_automation(backend, "auto_1", "Keep temp steady")
    backend.assign_category("automation", identity, "automation", "cat_hvac")
    plan_hash = sha256_hash(backend.list_remote("automation")[identity])
    backend.reset_write_tracking()

    manifest = _manifest_with_category(
        "automation:auto_1", plan_hash, "automatic_hvac", "automatic_hvac.py"
    )
    plan = Plan(
        entries=[
            _update_entry(
                "automation:auto_1",
                "automation",
                {"id": "auto_1", "alias": "Keep temp steady"},
                plan_hash,
                "automatic_hvac.py",
            )
        ]
    )
    result = apply_plan(plan, backend, manifest)

    assert result.succeeded is True
    assert result.category_conflicts == []
    assert backend.categories_for("automation", identity) == {"automation": "cat_hvac"}
    new_entry = result.manifest.objects["automation:auto_1"]  # type: ignore[union-attr]
    assert new_entry.category == "automatic_hvac"
