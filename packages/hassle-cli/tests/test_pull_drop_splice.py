"""Regression: `hassle pull`'s DROP must remove ONLY the deleted object's
statement (M2's LibCST splicer, DESIGN §7.3), never unlink the whole file.

Same class as the REFRESH clobber (`test_pull_refresh_splice.py`, found on
main at 748b461): `hassle.sync.pull_apply._drop` calls
`SourceWriter.delete_object`, and `WholeFileSourceWriter.delete_object` -- the
writer `hassle_cli.cli.pull` handed it -- unlinked the ENTIRE file
(`path.unlink()`), even when sibling objects and hand-written comments lived
in it. I6: deleting one automation in the HA UI silently destroyed every
local sibling sharing its source file.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from hassle.compiler import compile_bundle

TWO_AUTOMATIONS = """\
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
"""

# TWO_AUTOMATIONS minus exactly the hall def: the survivor (imports, the
# hand-written comment, the porch def) must come through byte-identical.
EXPECTED_AFTER_DROP = """\
from hassle import automation, service, state, when


# Hand-written note about the porch automation. Do not lose this comment.
@automation(id="porch_light_on_motion", alias="Porch light on motion")
def porch_light_on_motion():
    when(state("binary_sensor.porch_motion").to("on"))
    service("light.turn_on", target={"entity_id": "light.porch"})
"""


def _commit_all(repo: Path, message: str) -> None:
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", message], cwd=repo, check=True, capture_output=True
    )


def _push_two_automations_then_delete_hall_remotely(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    (git_repo / "hallway.py").write_text(TWO_AUTOMATIONS, encoding="utf-8")
    _commit_all(git_repo, "two automations in one file")

    # Push both objects; the manifest now tracks them with a shared source file.
    assert cli(["push", "--yes"], cwd=git_repo).exit_code == 0
    _commit_all(git_repo, "pushed")

    # Delete ONLY hall_light_on_motion remotely (simulating a UI deletion).
    backend.delete("automation", "hall_light_on_motion")


def test_pull_drop_preserves_sibling_objects_in_same_file(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    _push_two_automations_then_delete_hall_remotely(git_repo, cli, fake_backend, toml_writer)

    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code == 0, result.output

    # THE regression: the whole-file writer unlinked hallway.py entirely; only
    # the dropped object's statement may go -- the sibling def and its
    # hand-written comment survive byte-identical.
    assert (git_repo / "hallway.py").exists()
    after = (git_repo / "hallway.py").read_text(encoding="utf-8")
    assert after == EXPECTED_AFTER_DROP, after

    # The survivor still compiles from disk under its original id (I2); the
    # dropped object is really gone.
    compiled = compile_bundle(git_repo)
    assert "automation:porch_light_on_motion" in compiled.objects, sorted(compiled.objects)
    assert "automation:hall_light_on_motion" not in compiled.objects, sorted(compiled.objects)


def test_pull_drop_then_plan_is_noop(git_repo: Path, cli, fake_backend, toml_writer) -> None:
    # The drop must also retire the object's manifest entry: a plan right
    # after the pull has nothing left to do for either object (the dropped one
    # is gone on all three sides; the survivor is unchanged).
    from hassle.sync.models import PlanAction
    from hassle_cli.cli import _build_plan

    _push_two_automations_then_delete_hall_remotely(git_repo, cli, fake_backend, toml_writer)
    assert cli(["pull"], cwd=git_repo).exit_code == 0

    plan = _build_plan(git_repo)
    non_noop = {
        e.object_key: e.action.value for e in plan.entries if e.action is not PlanAction.NOOP
    }
    assert non_noop == {}, non_noop
