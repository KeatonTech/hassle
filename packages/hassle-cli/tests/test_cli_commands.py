"""CLI-level tests with `FakeBackend` for every command -- exit codes,
output snapshots (rich rendering tested via captured plain-text mode).

Commands under test: init, login, pull, status, plan, push, validate, test, run,
fmt, stubs, explain, render, doctor.
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
    assert (project / "lib").is_dir()
    assert (project / "tests").is_dir()
    assert (project / ".github" / "workflows").is_dir()
    # git init offered by default in a non-repo dir
    assert (project / ".git").is_dir()


def test_init_scaffolds_the_full_design_section_6_tree(tmp_path: Path, cli) -> None:
    """`hassle init` follows the category-first tree layout (DESIGN §6) --
    `lib/`/`tests/` are real scaffolded directories; the OLD per-kind trees
    (`automations/`, `scripts/`, `helpers/`) are RETIRED (root-level
    `<slug>.py` files are the layout now, created on demand by the
    compiler/decompiler, not scaffolded empty directories). No `__init__.py`
    is written (the loader uses PEP 420 namespace packages, docs/
    ha-api-notes.md §17.9 RESOLVED)."""
    project = tmp_path / "new-house"
    project.mkdir()
    result = cli(["init"], cwd=project)
    assert result.exit_code == 0, result.output
    for name in ("lib", "tests"):
        assert (project / name).is_dir(), f"missing {name}/"
        assert not (project / name / "__init__.py").exists(), (
            f"{name}/__init__.py should not be scaffolded -- namespace packages need none"
        )
    for retired in ("automations", "scripts", "helpers"):
        assert not (project / retired).exists(), (
            f"{retired}/ is a RETIRED per-kind tree -- must not be scaffolded"
        )


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
    (root / "hassle.toml").write_text("format_version = 1\n", encoding="utf-8")
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


def test_validate_json_clean_bundle(bundle_dir: Path, cli) -> None:
    import json

    result = cli(["validate", "--json"], cwd=bundle_dir)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload == {"findings": []}


def test_validate_json_reports_findings_with_stable_schema(
    tmp_path: Path, cli, registry_snapshot_json
) -> None:
    # `hassle validate --json` is the shared contract with the VS Code
    # extension's Problems-pane integration -- one JSON object with a
    # `findings` array, each Finding surfacing exactly the fields the
    # extension maps to a `vscode.Diagnostic` (file/line/severity/code/
    # message/fix), snapshot-tested on both sides.
    import json

    root = tmp_path / "broken-house"
    root.mkdir()
    (root / ".hassle").mkdir()
    (root / ".hassle" / "registry.json").write_text(
        json.dumps(registry_snapshot_json), encoding="utf-8"
    )
    (root / "hassle.toml").write_text("format_version = 1\n", encoding="utf-8")
    (root / "a.py").write_text(
        """
from hassle import automation, service

@automation(id="a", alias="A")
def a():
    service("light.turn_on", target={"entity_id": "light.halway"})
""",
        encoding="utf-8",
    )
    result = cli(["validate", "--json"], cwd=root)
    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert set(payload) == {"findings"}
    assert len(payload["findings"]) >= 1
    finding = payload["findings"][0]
    assert set(finding) == {"code", "severity", "file", "line", "message", "fix"}
    assert finding["file"] == "a.py"
    assert isinstance(finding["line"], int)
    assert "halway" in finding["message"]


def test_validate_json_output_has_no_rich_markup(bundle_dir: Path, cli) -> None:
    # The JSON mode must never be wrapped in the human [red]/[green] rich
    # markup the plain-text renderer uses elsewhere -- an editor extension
    # parses this stdout directly as JSON.
    result = cli(["validate", "--json"], cwd=bundle_dir)
    assert "[green]" not in result.output
    assert "[red]" not in result.output


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
    #
    # The stub must live at `typings/hassle/registry/__init__.pyi` (a
    # pyright custom-stubPath location), NOT `.hassle/entities.pyi` -- the
    # latter is not on any import path pyright resolves `hassle.registry` to,
    # so a real editor never picked up the generated types at all
    # (`test_registry_stubs_pyright.py` proves the correct placement/config;
    # this command just never matched it -- see docs/ha-api-notes.md).
    stub_path = bundle_dir / "typings" / "hassle" / "registry" / "__init__.pyi"
    assert stub_path.is_file()
    assert not (bundle_dir / ".hassle" / "entities.pyi").exists()
    # Package marker so pyright treats the synthetic `hassle` stub package as
    # a regular package (mirrors test_registry_stubs_pyright.py's own setup).
    assert (bundle_dir / "typings" / "hassle" / "__init__.pyi").is_file()


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


def test_pull_writes_registry_snapshot(git_repo, cli, fake_backend, toml_writer) -> None:
    # DESIGN §9.2: the snapshot is "refreshed on every pull". Smoke test showed
    # validate skipping tier-2/3 right after a fresh pull because pull never
    # wrote .hassle/registry.json.
    import subprocess

    _backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    subprocess.run(["git", "add", "-A"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-qm", "scaffold"], cwd=git_repo, check=True)

    # The fixture pre-seeds registry.json; the refresh contract is that pull
    # RE-fetches it from the backend, so remove the seed first (and commit the
    # removal -- pull requires a clean tree).
    (git_repo / ".hassle" / "registry.json").unlink()
    subprocess.run(["git", "add", "-A"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-qm", "drop seeded registry"], cwd=git_repo, check=True)

    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code == 0, result.output
    assert (git_repo / ".hassle" / "registry.json").is_file(), result.output
