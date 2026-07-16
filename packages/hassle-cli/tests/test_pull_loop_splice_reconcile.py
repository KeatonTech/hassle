"""`hassle pull` warns when a REFRESH's splice-append path fires for a
metaprogrammed (compile-time-loop-generated) object.

Splicing a UI edit for an object that only exists via a compile-time `for`
loop has no single literal statement to replace, so
`SplicingSourceWriter.splice_object` appends the refreshed definition
standalone -- the very next compile then raises `DuplicateObjectError` (the
loop iteration and the appended def both declare the same id). This test
pins the pull-time warning that explains the situation and points at the
reconcile flow BEFORE that failure surprises the user on their next
`hassle validate`/`hassle test`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from hassle.compiler import DuplicateObjectError, compile_bundle

LOOP_GENERATED_ROOMS = """\
from hassle import automation, service, state, when

ROOMS = ["kitchen", "office"]

for room in ROOMS:

    @automation(id=f"motion_{room}", alias=f"Motion light: {room}")
    def _motion(room: str = room):
        when(state(f"binary_sensor.{room}_motion").to("on"))
        service("light.turn_on", entity_id=f"light.{room}")
"""


def _commit_all(repo: Path, message: str) -> None:
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", message], cwd=repo, check=True, capture_output=True
    )


def test_pull_warns_on_loop_splice_reconcile(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    (git_repo / "rooms.py").write_text(LOOP_GENERATED_ROOMS, encoding="utf-8")
    _commit_all(git_repo, "loop-generated automations")

    assert cli(["push", "--yes"], cwd=git_repo).exit_code == 0
    _commit_all(git_repo, "pushed")

    # Drift ONE loop-generated automation remotely (simulating a UI edit) --
    # the splicer has no single literal statement for "motion_kitchen" to
    # replace (it's parameterized inside the loop), so it must append.
    remote = backend.list_remote("automation")["motion_kitchen"]
    backend.update(
        "automation",
        "motion_kitchen",
        {**remote, "alias": "Motion light: kitchen (UI edit)"},
    )

    result = cli(["pull", "--allow-dirty"], cwd=git_repo)
    # The append lands (nothing lost) but the bundle now has a genuine
    # duplicate id -- pull's post-write compile backstop catches that (exit
    # 1), with framing that recognizes this as the EXPECTED consequence of
    # the reconcile warning above, never "a bug in Hassle's decompiler".
    assert result.exit_code == 1, result.output

    lowered = result.output.lower()
    assert "automation:motion_kitchen" in lowered
    assert "metaprogramming" in lowered
    assert "fold" in lowered
    assert "extract" in lowered
    assert "delete" in lowered
    assert "validate" in lowered
    assert "this is expected, not a hassle bug" in lowered
    assert "bug in hassle's decompiler" not in lowered

    # Nothing was lost -- the loop is intact and the UI edit landed,
    # appended under the marker, despite the post-write compile failing.
    after = (git_repo / "rooms.py").read_text(encoding="utf-8")
    assert "for room in ROOMS:" in after
    assert "Motion light: kitchen (UI edit)" in after
    assert "# hassle: updated from UI on " in after

    # And the NEXT compile of this bundle is exactly the DuplicateObjectError
    # the warning promised -- this is a real, load-bearing situation, not a
    # false alarm.
    with pytest.raises(DuplicateObjectError) as excinfo:
        compile_bundle(git_repo)
    assert "loop-splice reconcile" in str(excinfo.value)


def test_pull_does_not_warn_for_an_ordinary_refresh(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    # Sanity/regression: an ordinary (non-metaprogrammed) refresh must not
    # emit the reconcile warning.
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    (git_repo / "hallway.py").write_text(
        "from hassle import automation, service, state, when\n\n\n"
        '@automation(id="hall_light_on_motion", alias="Hallway light on motion")\n'
        "def hall_light_on_motion():\n"
        '    when(state("binary_sensor.hall_motion").to("on"))\n'
        '    service("light.turn_on", target={"entity_id": "light.hallway"})\n',
        encoding="utf-8",
    )
    _commit_all(git_repo, "one automation")
    assert cli(["push", "--yes"], cwd=git_repo).exit_code == 0
    _commit_all(git_repo, "pushed")

    remote = backend.list_remote("automation")["hall_light_on_motion"]
    backend.update(
        "automation",
        "hall_light_on_motion",
        {**remote, "alias": "Hallway light on motion (UI edit)"},
    )

    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code == 0, result.output
    assert "metaprogramming" not in result.output.lower()
    assert "reconcile" not in result.output.lower()
