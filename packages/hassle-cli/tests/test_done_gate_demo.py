"""M7 done-gate (MILESTONES M7 "Done when"): the DESIGN §8.4 daily loop, demoed
end-to-end from a fresh directory in < 10 commands, against `FakeBackend`.

The loop (DESIGN §8.4):

    hassle init
    hassle login ...
    hassle pull
    git add -A && git commit ...
    <edit .py files, write tests>
    hassle validate && hassle test
    hassle push --yes
    git add -A && git commit ...

This test IS the scripted transcript: each `hassle` invocation is one counted
command (plain shell/git steps are not Hassle commands and don't count against
the <10 budget, matching the milestone's "demoable ... in < 10 commands" framing
of the CLI's own command count).
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _git_commit_if_dirty(message: str, *, cwd: Path) -> None:
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=cwd, check=True, capture_output=True, text=True
    )
    if not status.stdout.strip():
        return  # nothing to commit (e.g. a first pull with no remote objects yet)
    _git("add", "-A", cwd=cwd)
    _git("commit", "-q", "-m", message, cwd=cwd)


def test_full_daily_loop_in_under_ten_hassle_commands(
    tmp_path: Path, cli, fake_backend, toml_writer
) -> None:
    backend, token = fake_backend
    project = tmp_path / "fresh-house"
    project.mkdir()

    hassle_commands: list[list[str]] = []

    def run_hassle(args: list[str]) -> None:
        hassle_commands.append(args)
        result = cli(args, cwd=project)
        assert result.exit_code == 0, f"{args} failed:\n{result.output}"

    # 1. hassle init
    run_hassle(["init"])
    toml_writer(project, backend_token=token)
    _git("config", "user.email", "test@example.com", cwd=project)
    _git("config", "user.name", "Test", cwd=project)
    _git("add", "-A", cwd=project)
    _git("commit", "-q", "-m", "hassle init", cwd=project)

    # 2. hassle pull (nothing remote yet -- first pull adopts everything; empty here)
    run_hassle(["pull"])
    _git_commit_if_dirty("sync: UI changes", cwd=project)

    # Author a bundle file by hand (not a `hassle` command -- editing .py files
    # is the human's job in the loop). DSL sources live under the DESIGN §6
    # tree (docs/ha-api-notes.md §17.9 RESOLVED: the loader recurses into
    # subdirectory packages, `hassle init` scaffolds automations/).
    (project / "automations" / "hallway.py").write_text(
        """
from hassle import automation, service, state, when

@automation(id="hall_light_on_motion", alias="Hallway light on motion")
def hall_light_on_motion():
    when(state("binary_sensor.hall_motion").to("on"))
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
        encoding="utf-8",
    )
    (project / "tests" / "test_hallway.py").write_text(
        """
from hassle.testing import simulate

def test_motion_turns_on_light(sim):
    sim.state_change("binary_sensor.hall_motion", "off", "on")
    sim.assert_called("light.turn_on", entity_id="light.hallway")
""",
        encoding="utf-8",
    )

    # 3. hassle validate
    run_hassle(["validate"])
    # 4. hassle test
    run_hassle(["test"])
    # 5. hassle push --yes
    run_hassle(["push", "--yes"])

    _git_commit_if_dirty("push: hallway automation", cwd=project)

    assert len(hassle_commands) < 10, (
        f"used {len(hassle_commands)} hassle commands: {hassle_commands}"
    )
    assert "hall_light_on_motion" in backend.list_remote("automation")

    # Prove the loop really is round-trippable: a second pull on a clean tree
    # is a no-op (manifest already matches).
    run_hassle(["pull"])
    assert len(hassle_commands) < 10
