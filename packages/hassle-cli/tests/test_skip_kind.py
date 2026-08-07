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


# -- end-to-end through the real CLI -----------------------------------------


def _commit_all(bundle, message: str) -> None:
    import subprocess

    subprocess.run(["git", "add", "-A"], cwd=bundle, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", message], cwd=bundle, check=True, capture_output=True
    )


def _seed_dashboard(backend) -> None:
    backend.create(
        "dashboard",
        {
            "meta": {"url_path": "dashboard-home", "title": "Home"},
            "config": {"views": [{"title": "Overview", "cards": []}]},
        },
    )


def test_plan_without_the_flag_shows_the_dashboard(git_repo, cli, fake_backend, toml_writer):
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    _seed_dashboard(backend)
    result = cli(["plan"], cwd=git_repo)
    assert result.exit_code == 0, result.output
    assert "dashboard:dashboard-home" in result.output


def test_plan_with_skip_kind_hides_the_dashboard(git_repo, cli, fake_backend, toml_writer):
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    _seed_dashboard(backend)
    result = cli(["plan", "--skip-kind", "dashboard"], cwd=git_repo)
    assert result.exit_code == 0, result.output
    assert "dashboard:dashboard-home" not in result.output


def test_pull_with_skip_kind_writes_no_dashboard_file(git_repo, cli, fake_backend, toml_writer):
    """The point of the flag: a dashboard the bundle has never adopted stays
    unadopted, so no `dashboards/` file appears."""
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    _seed_dashboard(backend)
    _commit_all(git_repo, "point at fake backend")

    result = cli(["pull", "--skip-kind", "dashboard"], cwd=git_repo)
    assert result.exit_code == 0, result.output
    assert not (git_repo / "dashboards").exists(), sorted(q.name for q in git_repo.iterdir())

    # ...and without the flag the very same bundle DOES adopt it, so the test
    # above is not passing vacuously. (The skipped pull still adopts the other
    # kinds and regenerates stubs, so commit before pulling again -- pull
    # refuses a dirty tree.)
    _commit_all(git_repo, "after the skipped pull")
    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code == 0, result.output
    assert (git_repo / "dashboards" / "dashboard_home.py").is_file()


def test_push_with_skip_kind_never_writes_the_dashboard_to_ha(
    git_repo, cli, fake_backend, toml_writer
):
    """THE safety property end-to-end: with the kind skipped, a push must not
    create/update/delete anything of that kind on the backend."""
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    (git_repo / "dashboards").mkdir()
    (git_repo / "dashboards" / "home.py").write_text(
        "from hassle import *\n\n\n"
        '@dashboard(url_path="dashboard-home", title="Home")\n'
        "def home():\n"
        '    with view(title="Overview"):\n'
        "        pass\n",
        encoding="utf-8",
    )
    _commit_all(git_repo, "declare a dashboard")

    dashboards_before = dict(backend.list_remote("dashboard"))
    result = cli(["push", "--yes", "--skip-kind", "dashboard"], cwd=git_repo)
    assert result.exit_code == 0, result.output

    # Nothing of the skipped kind reached HA...
    assert backend.list_remote("dashboard") == dashboards_before
    assert "dashboard-home" not in backend.list_remote("dashboard")
    # ...while the run was otherwise a normal push, so this is not vacuous:
    # the bundle's automation was created as usual.
    assert "create automation:" in result.output, result.output
    assert "skipped dashboard:dashboard-home" in result.output, result.output


def test_unknown_skip_kind_fails_loudly(git_repo, cli, fake_backend, toml_writer):
    """A typo must not silently skip nothing while every dashboard is pushed."""
    _backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    result = cli(["plan", "--skip-kind", "dashboards"], cwd=git_repo)
    assert result.exit_code == 1, result.output
    assert "dashboards" in result.output
    assert "Fix:" in result.output
