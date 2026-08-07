"""`--skip-kind` on `pull`/`plan`/`status`/`push`: exclude a whole object kind
from ONE run, without changing the bundle's configuration.

Motivating case (real household, 2026-07-29): dashboards are the newest kind
and the one most likely to churn from UI edits, so an operator wants to run
`hassle pull --skip-kind dashboard` and keep their automations in sync without
adopting or re-writing eight dashboards each time.

This is the TRANSIENT sibling of `hassle.toml`'s `ignore` globs, and the
difference is the whole design:

- `ignore` is permanent and *unmanages* an object: `migrate_manifest_for_ignores`
  DROPS its manifest entry, so Hassle forgets the object's sync base.
- `--skip-kind` is per-invocation and must be a pure no-op: the object stays
  managed, its manifest entry is preserved byte-for-byte, and the next run
  without the flag behaves exactly as if the skipped run had not happened.

That is why the filter runs over PLAN ENTRIES rather than over the manifest:
`hassle.sync.apply._advance_manifest` starts from `dict(manifest.objects)` and
only rewrites keys that appear in the plan, so dropping an entry from the plan
leaves that object's manifest state untouched by construction.
"""

from __future__ import annotations

from hassle.sync.models import Manifest, ManifestEntry, PlanAction
from hassle.sync.plan import compute_plan
from hassle_cli.skip_kind import drop_skipped_kinds, parse_skip_kinds

_AUTOMATION_CFG = {"id": "a", "alias": "A", "triggers": [], "conditions": [], "actions": []}
_DASHBOARD_CFG = {
    "meta": {"url_path": "dashboard-home", "title": "Home"},
    "config": {"views": [{"title": "Overview", "cards": []}]},
}


def _manifest(**objects: ManifestEntry) -> Manifest:
    return Manifest(synced_at="2026-01-01T00:00:00Z", ha_version="2026.7.4", objects=objects)


def test_parse_skip_kinds_accepts_known_kinds() -> None:
    assert parse_skip_kinds(("dashboard",)) == frozenset({"dashboard"})
    assert parse_skip_kinds(("dashboard", "script")) == frozenset({"dashboard", "script"})
    assert parse_skip_kinds(()) == frozenset()


def test_parse_skip_kinds_rejects_an_unknown_kind_with_a_teaching_error() -> None:
    import pytest

    with pytest.raises(ValueError) as exc:
        parse_skip_kinds(("dashboards",))  # plural typo -- the likely mistake
    message = str(exc.value)
    assert "dashboards" in message
    assert "dashboard" in message  # names the valid spelling
    assert "Fix:" in message


def test_skipped_kind_entries_are_dropped_from_the_plan() -> None:
    plan = compute_plan(
        manifest=_manifest(),
        local_objects={
            "automation:a": ("automation", _AUTOMATION_CFG),
            "dashboard:dashboard-home": ("dashboard", _DASHBOARD_CFG),
        },
        remote_objects={},
    )
    assert {e.object_key for e in plan.entries} == {"automation:a", "dashboard:dashboard-home"}

    filtered = drop_skipped_kinds(plan, frozenset({"dashboard"}))
    assert {e.object_key for e in filtered.plan.entries} == {"automation:a"}
    assert filtered.skipped_keys == ["dashboard:dashboard-home"]


def test_skipping_nothing_returns_the_plan_untouched() -> None:
    plan = compute_plan(
        manifest=_manifest(),
        local_objects={"automation:a": ("automation", _AUTOMATION_CFG)},
        remote_objects={},
    )
    filtered = drop_skipped_kinds(plan, frozenset())
    assert filtered.plan is plan
    assert filtered.skipped_keys == []


def test_skip_never_plans_a_delete_for_a_locally_removed_dashboard() -> None:
    """THE safety property, mirroring `ignore`'s: a dashboard that exists
    remotely and in the manifest but is absent locally would normally plan a
    `delete`. With the kind skipped, it must produce no entry at all -- a
    skipped run can never write to HA for that kind."""
    manifest = _manifest(
        **{
            "dashboard:dashboard-home": ManifestEntry(
                source="dashboards/dashboard_home.py", compiled_hash="deadbeef"
            )
        }
    )
    plan = compute_plan(
        manifest=manifest,
        local_objects={},
        remote_objects={"dashboard:dashboard-home": ("dashboard", _DASHBOARD_CFG)},
    )
    assert plan.entries[0].action is not PlanAction.NOOP  # it really would act

    filtered = drop_skipped_kinds(plan, frozenset({"dashboard"}))
    assert filtered.plan.entries == []


def test_skip_preserves_the_manifest_entry_so_the_next_run_is_unaffected() -> None:
    """The invariant that separates `--skip-kind` from `ignore`: the skipped
    object stays MANAGED. Its manifest entry must survive a skipped run
    untouched, so a later run without the flag sees the same sync base."""
    entry = ManifestEntry(source="dashboards/dashboard_home.py", compiled_hash="deadbeef")
    manifest = _manifest(**{"dashboard:dashboard-home": entry})

    plan = compute_plan(
        manifest=manifest,
        local_objects={"dashboard:dashboard-home": ("dashboard", _DASHBOARD_CFG)},
        remote_objects={},
    )
    filtered = drop_skipped_kinds(plan, frozenset({"dashboard"}))

    # The filter touches only the plan -- the manifest it was computed from is
    # the same object, entry-for-entry.
    assert manifest.objects["dashboard:dashboard-home"] == entry
    assert filtered.plan.entries == []
