"""MILESTONES M7 test 4: `test_conflict_ux_snapshot` -- 3-way DSL diff output golden."""

from __future__ import annotations

import os
from pathlib import Path

SNAP_DIR = Path(__file__).resolve().parent / "snapshots"


def _check_snapshot(name: str, actual: str) -> None:
    actual = actual.rstrip("\n")
    path = SNAP_DIR / f"{name}.txt"
    if os.environ.get("HASSLE_UPDATE_SNAPSHOTS"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual + "\n", encoding="utf-8")
    assert path.is_file(), f"missing snapshot {path}; set HASSLE_UPDATE_SNAPSHOTS=1 to write it"
    assert actual == path.read_text(encoding="utf-8").rstrip("\n")


def test_plan_renders_conflict_with_3way_dsl_diff(
    git_repo: Path, cli, fake_backend, tmp_path: Path, toml_writer, output_normalizer
) -> None:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    assert cli(["push", "--yes"], cwd=git_repo).exit_code == 0

    # Edit remotely (simulating a UI edit) ...
    remote = backend.list_remote("automation")["hall_light_on_motion"]
    remote_edited = {**remote, "alias": "Hallway light on motion (UI edit)"}
    backend.update("automation", "hall_light_on_motion", remote_edited)

    # ... and locally, to a *different* value -> both_edited conflict.
    (git_repo / "hallway.py").write_text(
        """
from hassle import automation, service, state, when

@automation(id="hall_light_on_motion", alias="Hallway light on motion (local edit)")
def hall_light_on_motion():
    when(state("binary_sensor.hall_motion").to("on"))
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
        encoding="utf-8",
    )

    result = cli(["plan"], cwd=git_repo)
    assert result.exit_code == 0, result.output
    assert "conflict" in result.output.lower()
    assert "local" in result.output.lower()
    assert "remote" in result.output.lower()
    _check_snapshot("conflict_3way_diff", output_normalizer(result.output, tmp_path))


def test_push_aborts_on_unresolved_conflict(git_repo: Path, cli, fake_backend, toml_writer) -> None:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    assert cli(["push", "--yes"], cwd=git_repo).exit_code == 0

    remote = backend.list_remote("automation")["hall_light_on_motion"]
    backend.update("automation", "hall_light_on_motion", {**remote, "alias": "UI edit"})
    (git_repo / "hallway.py").write_text(
        """
from hassle import automation, service, state, when

@automation(id="hall_light_on_motion", alias="Local edit")
def hall_light_on_motion():
    when(state("binary_sensor.hall_motion").to("on"))
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
        encoding="utf-8",
    )

    result = cli(["push", "--yes"], cwd=git_repo)
    assert result.exit_code != 0
    assert "conflict" in result.output.lower()
    assert "--accept-local" in result.output
    assert "--accept-remote" in result.output


def test_push_accept_local_resolves_conflict(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    assert cli(["push", "--yes"], cwd=git_repo).exit_code == 0

    remote = backend.list_remote("automation")["hall_light_on_motion"]
    backend.update("automation", "hall_light_on_motion", {**remote, "alias": "UI edit"})
    (git_repo / "hallway.py").write_text(
        """
from hassle import automation, service, state, when

@automation(id="hall_light_on_motion", alias="Local edit")
def hall_light_on_motion():
    when(state("binary_sensor.hall_motion").to("on"))
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
        encoding="utf-8",
    )

    result = cli(
        ["push", "--yes", "--accept-local", "automation:hall_light_on_motion"], cwd=git_repo
    )
    assert result.exit_code == 0, result.output
    assert backend.list_remote("automation")["hall_light_on_motion"]["alias"] == "Local edit"
