"""Dashboard-kind CLI smoke tests (docs/internals/dashboards-design.md §7):

- `hassle plan`/`status`/`pull` kind lists are `OBJECT_KINDS`-driven
  (`bundle_ops.remote_objects_from_backend(backend, list(OBJECT_KINDS))`), so
  they need no per-kind code to pick up the new `dashboard` kind -- pinned
  here against a bundle/backend with no dashboards at all, proving the
  kind's mere presence in `OBJECT_KINDS` doesn't break the commands that loop
  over every kind.
- `hassle explain` renders a compiled object generically (`explain.as_yaml`
  is a thin `yaml.safe_dump` over whatever dict it's given) -- verified
  directly against a `DashboardConfig` envelope's `to_ha()` output, since
  nothing in this repo can compile a real `@dashboard`/`@raw_dashboard` body
  yet (workstreams DB2/DB3).

`hassle.backend.fake.FakeBackend`'s own dashboard CRUD support is workstream
DB5's scope and isn't needed for the smoke tests below: `list_remote` is
already kind-generic (see the module docstring of
`test_pull_dashboards_placement.py` for the same point re: `create`).
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
