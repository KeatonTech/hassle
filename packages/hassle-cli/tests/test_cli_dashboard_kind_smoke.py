"""Dashboard-kind CLI smoke tests (docs/internals/dashboards-design.md §7):

- `hassle plan`/`status`/`pull` kind lists are `OBJECT_KINDS`-driven
  (`bundle_ops.remote_objects_from_backend(backend, list(OBJECT_KINDS))`), so
  they need no per-kind code to pick up the new `dashboard` kind -- pinned
  against a bundle/backend with no dashboards at all (proving the kind's
  mere presence in `OBJECT_KINDS` doesn't break the commands that loop over
  every kind) AND, non-vacuously, against a backend that HAS a seeded
  dashboard (proving `hassle plan` actually surfaces it as `adopt
  dashboard:<url_path>` -- the empty-backend smoke tests alone would still
  pass with the whole feature reverted).
- `hassle explain` renders a compiled object generically (`explain.as_yaml`
  is a thin `yaml.safe_dump` over whatever dict it's given) -- verified
  directly against a `DashboardConfig` envelope's `to_ha()` output, since
  nothing in this repo can compile a real `@dashboard`/`@raw_dashboard` body
  yet (workstreams DB2/DB3).

`hassle.backend.fake.FakeBackend` has real dashboard CRUD support (DB5
landed) -- used directly below via `backend.create("dashboard", ...)`, same
as every other kind's CLI tests.

**Explicit DB4 handoff item**: nothing here attempts an end-to-end `hassle
pull` against a backend with a seeded dashboard -- that currently dies
inside `hassle.decompiler.decompile_bundle` (no dispatch branch for
`DashboardConfig` yet). The PLAN-level assertion below is deliberately as
far as this workstream goes; DB4 owns the pull-side gap once the decompiler
branch lands (see also `test_pull_dashboards_placement.py`'s module
docstring).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from hassle.ir.keys import DASHBOARD_KIND, OBJECT_KINDS
from hassle.ir.models import DashboardConfig
from hassle_cli.explain import as_yaml


def _commit_all(bundle: Path, message: str) -> None:
    subprocess.run(["git", "add", "-A"], cwd=bundle, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", message], cwd=bundle, check=True, capture_output=True
    )


def test_dashboard_kind_is_registered() -> None:
    assert DASHBOARD_KIND in OBJECT_KINDS


def test_plan_runs_clean_with_dashboard_kind_registered_and_no_dashboards(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    _backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    result = cli(["plan"], cwd=git_repo)
    assert result.exit_code == 0, result.output


def test_status_runs_clean_with_dashboard_kind_registered_and_no_dashboards(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    _backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    result = cli(["status"], cwd=git_repo)
    assert result.exit_code == 0, result.output


def test_plan_shows_adopt_for_a_seeded_dashboard(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    # Non-vacuous (reviewer note): the two smoke tests above pass even with
    # the whole dashboard feature reverted, since there are no dashboards to
    # find. This one seeds a real dashboard on the (real, DB5-backed)
    # FakeBackend and asserts `hassle plan` actually reports it as an ADOPT --
    # plan-level only (see the module docstring for why pull isn't exercised
    # here).
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    backend.create(
        "dashboard",
        {
            "meta": {"url_path": "climate-control", "title": "Climate"},
            "config": {"views": []},
        },
    )
    result = cli(["plan"], cwd=git_repo)
    assert result.exit_code == 0, result.output
    assert "adopt" in result.output, result.output
    assert "dashboard:climate-control" in result.output, result.output


def test_pull_runs_clean_with_dashboard_kind_registered_and_no_dashboards(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    _backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    _commit_all(git_repo, "point at fake backend")
    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code == 0, result.output


def test_explain_renders_dashboard_envelope_generically() -> None:
    dashboard = DashboardConfig.model_validate(
        {
            "meta": {
                "url_path": "climate-control",
                "title": "Climate",
                "icon": "mdi:thermostat",
                "show_in_sidebar": True,
                "require_admin": False,
            },
            "config": {
                "views": [
                    {
                        "title": "Overview",
                        "cards": [{"type": "tile", "entity": "climate.living_room"}],
                    }
                ]
            },
        }
    )
    rendered = as_yaml(dashboard.to_ha())
    assert "climate-control" in rendered
    assert "views" in rendered
    assert "tile" in rendered


def test_explain_renders_default_dashboard_envelope_with_null_meta() -> None:
    dashboard = DashboardConfig.model_validate(
        {"meta": None, "config": {"views": [{"title": "Home", "cards": []}]}}
    )
    rendered = as_yaml(dashboard.to_ha())
    assert "views" in rendered
    assert "Home" in rendered
