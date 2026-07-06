"""Regression: `hassle pull`'s REFRESH must splice ONLY the drifted object's
def in place (M2's LibCST splicer, DESIGN §7.3), never rewrite the whole file.

Found while implementing ux/triggers-in-decorator (pre-existing on main at
748b461): `hassle_cli.cli.pull` handed `apply_pull_with_decompiler` a
`WholeFileSourceWriter`, whose `splice_object` is the documented M5 whole-file
overwrite stand-in -- so refreshing one drifted object clobbered every sibling
object (and every hand-written comment) sharing its source file. I6: a local
edit (the sibling def, the comment) was silently lost.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from hassle.compiler import compile_bundle

TWO_AUTOMATIONS = '''\
from hassle import automation, service, state, when


@automation(id="hall_light_on_motion", alias="Hallway light on motion")
def hall_light_on_motion():
    when(state("binary_sensor.hall_motion").to("on"))
    service("light.turn_on", target={"entity_id": "light.hallway"})


# Hand-written note about the porch automation. Do not lose this comment.
@automation(id="porch_light_on_motion", alias="Porch light on motion")
def porch_light_on_motion():
    when(state("binary_sensor.porch_motion").to("on"))
    service("light.turn_on", target={"entity_id": "light.porch"})
'''


def _commit_all(repo: Path, message: str) -> None:
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", message], cwd=repo, check=True, capture_output=True
    )


def test_pull_refresh_preserves_sibling_objects_in_same_file(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    (git_repo / "hallway.py").write_text(TWO_AUTOMATIONS, encoding="utf-8")
    _commit_all(git_repo, "two automations in one file")

    # Push both objects; the manifest now tracks them with a shared source file.
    assert cli(["push", "--yes"], cwd=git_repo).exit_code == 0
    _commit_all(git_repo, "pushed")

    # Drift ONLY hall_light_on_motion remotely (simulating a UI edit).
    remote = backend.list_remote("automation")["hall_light_on_motion"]
    backend.update(
        "automation",
        "hall_light_on_motion",
        {**remote, "alias": "Hallway light on motion (UI edit)"},
    )

    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code == 0, result.output

    after = (git_repo / "hallway.py").read_text(encoding="utf-8")
    # THE regression: the untouched sibling def and its hand-written comment
    # must survive the refresh of hall_light_on_motion byte-for-byte.
    assert (
        "# Hand-written note about the porch automation. Do not lose this comment.\n"
        '@automation(id="porch_light_on_motion", alias="Porch light on motion")\n'
        "def porch_light_on_motion():\n"
        '    when(state("binary_sensor.porch_motion").to("on"))\n'
        '    service("light.turn_on", target={"entity_id": "light.porch"})\n'
    ) in after, after
    # The drifted object's refreshed content did land.
    assert "Hallway light on motion (UI edit)" in after, after
    # And the spliced-in replacement carries the UI-update marker (DESIGN §7.3).
    assert "# hassle: updated from UI on " in after, after

    # Both objects still compile from disk under their original ids (I2).
    compiled = compile_bundle(git_repo)
    assert "automation:hall_light_on_motion" in compiled.objects, sorted(compiled.objects)
    assert "automation:porch_light_on_motion" in compiled.objects, sorted(compiled.objects)


def test_pull_refresh_then_plan_is_noop(git_repo: Path, cli, fake_backend, toml_writer) -> None:
    # The spliced file must re-establish the three-way-merge baseline: a plan
    # right after the refresh pull has nothing left to do for either object.
    from hassle.sync.models import PlanAction
    from hassle_cli.cli import _build_plan

    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    (git_repo / "hallway.py").write_text(TWO_AUTOMATIONS, encoding="utf-8")
    _commit_all(git_repo, "two automations in one file")
    assert cli(["push", "--yes"], cwd=git_repo).exit_code == 0
    _commit_all(git_repo, "pushed")

    remote = backend.list_remote("automation")["hall_light_on_motion"]
    backend.update(
        "automation",
        "hall_light_on_motion",
        {**remote, "alias": "Hallway light on motion (UI edit)"},
    )
    assert cli(["pull"], cwd=git_repo).exit_code == 0

    plan = _build_plan(git_repo)
    non_noop = {
        e.object_key: e.action.value for e in plan.entries if e.action is not PlanAction.NOOP
    }
    assert non_noop == {}, non_noop
