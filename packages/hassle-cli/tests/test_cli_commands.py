"""MILESTONES M7 test 1: CLI-level tests with `FakeBackend` for every command --
exit codes, output snapshots (rich rendering tested via captured plain-text mode).

Commands under test: init, login, pull, status, plan, push, validate, test, run,
fmt, stubs, explain, render, mirror, doctor.
"""

from __future__ import annotations

from pathlib import Path


def test_init_creates_bundle_scaffolding(tmp_path: Path, cli) -> None:
    project = tmp_path / "new-house"
    project.mkdir()
    result = cli(["init"], cwd=project)
    assert result.exit_code == 0, result.output
    assert (project / "hassle.toml").is_file()
    assert (project / ".gitignore").is_file()
    assert (project / "automations").is_dir()
    assert (project / "tests").is_dir()
    assert (project / ".github" / "workflows").is_dir()
    # git init offered by default in a non-repo dir
    assert (project / ".git").is_dir()


def test_init_is_idempotent(tmp_path: Path, cli) -> None:
    project = tmp_path / "new-house"
    project.mkdir()
    assert cli(["init"], cwd=project).exit_code == 0
    result = cli(["init"], cwd=project)
    assert result.exit_code == 0, result.output


def test_validate_clean_bundle_exits_zero(bundle_dir: Path, cli) -> None:
    result = cli(["validate"], cwd=bundle_dir)
    assert result.exit_code == 0, result.output


def test_validate_reports_findings_and_nonzero_exit(
    tmp_path: Path, cli, registry_snapshot_json
) -> None:
    import json

    root = tmp_path / "broken-house"
    root.mkdir()
    (root / ".hassle").mkdir()
    (root / ".hassle" / "registry.json").write_text(
        json.dumps(registry_snapshot_json), encoding="utf-8"
    )
    (root / "hassle.toml").write_text("format_version = 1\nmirror = false\n", encoding="utf-8")
    (root / "a.py").write_text(
        """
from hassle import automation, service

@automation(id="a", alias="A")
def a():
    service("light.turn_on", target={"entity_id": "light.halway"})
""",
        encoding="utf-8",
    )
    result = cli(["validate"], cwd=root)
    assert result.exit_code == 1
    assert "light.halway" in result.output
    assert "did you mean" in result.output.lower() or "hallway" in result.output.lower()


def test_status_shows_plan_and_git_status(git_repo: Path, cli, fake_backend, toml_writer) -> None:
    _backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    result = cli(["status"], cwd=git_repo)
    assert result.exit_code == 0, result.output
    assert "create" in result.output.lower()


def test_plan_shows_create_for_new_local_object(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    _backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    result = cli(["plan"], cwd=git_repo)
    assert result.exit_code == 0, result.output
    assert "automation:hall_light_on_motion" in result.output
    assert "create" in result.output.lower()


def test_push_creates_object_in_backend(git_repo: Path, cli, fake_backend, toml_writer) -> None:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    result = cli(["push", "--yes"], cwd=git_repo)
    assert result.exit_code == 0, result.output
    assert "hall_light_on_motion" in backend.list_remote("automation")


def test_pull_adopts_ui_created_object(git_repo: Path, cli, fake_backend, toml_writer) -> None:
    import subprocess

    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    # First push our local automation so the manifest has a baseline, then
    # commit push's own manifest.lock update (DESIGN §8.4: "your change + updated
    # manifest.lock" lands in the same commit) so the tree is clean for pull.
    assert cli(["push", "--yes"], cwd=git_repo).exit_code == 0
    subprocess.run(["git", "add", "-A"], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "push"], cwd=git_repo, check=True, capture_output=True
    )
    # Simulate a UI-created automation.
    backend.create(
        "automation",
        {
            "id": "ui_made_this",
            "alias": "UI made this",
            "triggers": [],
            "conditions": [],
            "actions": [],
            "mode": "single",
        },
    )
    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code == 0, result.output
    assert "ui_made_this" in result.output


def test_fmt_runs_without_error(bundle_dir: Path, cli) -> None:
    result = cli(["fmt"], cwd=bundle_dir)
    assert result.exit_code == 0, result.output


def test_stubs_generates_pyi_files(bundle_dir: Path, cli) -> None:
    result = cli(["stubs"], cwd=bundle_dir)
    assert result.exit_code == 0, result.output
    # `hassle.registry.stubs.generate_entities_stub` embeds typed service
    # methods on each domain's entity class -- there is no separate
    # services.pyi artifact (DESIGN §9.2/§5.2), just entities.pyi.
    assert (bundle_dir / ".hassle" / "entities.pyi").is_file()


def test_explain_renders_compiled_yaml_for_object(bundle_dir: Path, cli) -> None:
    result = cli(["explain", "automation:hall_light_on_motion"], cwd=bundle_dir)
    assert result.exit_code == 0, result.output
    assert "hall_light_on_motion" in result.output
    assert "binary_sensor.hall_motion" in result.output


def test_explain_unknown_object_key_clean_error(bundle_dir: Path, cli) -> None:
    result = cli(["explain", "automation:does_not_exist"], cwd=bundle_dir)
    assert result.exit_code != 0
    assert "does_not_exist" in result.output


def test_render_renders_template_offline_hint(bundle_dir: Path, cli) -> None:
    # Without --live, `render` on a template that needs a live jinja env still
    # renders through the simulator's template engine subset.
    result = cli(["render", "{{ 1 + 1 }}"], cwd=bundle_dir)
    assert result.exit_code == 0, result.output
    assert "2" in result.output


def test_test_command_runs_pytest_plugin(bundle_dir: Path, cli) -> None:
    (bundle_dir / "tests" / "test_hallway.py").write_text(
        """
def test_trivial():
    assert True
""",
        encoding="utf-8",
    )
    result = cli(["test"], cwd=bundle_dir)
    assert result.exit_code == 0, result.output


def test_doctor_clean_bundle_reports_ok(bundle_dir: Path, cli) -> None:
    result = cli(["doctor"], cwd=bundle_dir)
    assert result.exit_code == 0, result.output


def test_mirror_disabled_by_default_reports_status(
    bundle_dir: Path, cli, fake_backend, toml_writer
) -> None:
    _backend, token = fake_backend
    toml_writer(bundle_dir, backend_token=token)
    result = cli(["mirror", "status"], cwd=bundle_dir)
    assert result.exit_code == 0, result.output
    assert "disabled" in result.output.lower() or "off" in result.output.lower()
