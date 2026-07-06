"""`hassle pull`'s REFRESH splice emits the `triggers=` decorator form on disk
(ux/triggers-in-decorator, task #10) -- the real end-to-end path the milestone
text calls out ("spliced objects now emit decorator-form too").

`hassle_cli.pull_apply._refresh` calls `decompile_bundle` (already covered by
`packages/hassle-core/tests/test_decompile_triggers_in_decorator.py`) to build
the replacement text, then `splice_object` (LibCST) swaps just that one
top-level `def` in the existing file -- so this test is the belt-and-suspenders
check that the two compose correctly through the real CLI `pull` command.

Kept to a single-object-per-file scenario deliberately: a pre-existing,
unrelated bug (reproducible on main before this workstream, spawned as its own
follow-up task) means a REFRESH's on-disk result isn't actually a byte-preserving
LibCST splice in this test's harness (no `# hassle: updated from UI on` marker
survives, and a second object sharing the file gets dropped) -- this test only
asserts on the DECOMPILED CONTENT (decorator-form triggers, no `when()`, no
`# --- triggers ---`), which is this workstream's actual concern, not on
splice-preservation mechanics (already covered, with hand-written fixtures
immune to the pre-existing bug, by `packages/hassle-core/tests/test_splice.py`).
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def test_pull_refresh_splices_decorator_form_triggers(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    assert cli(["push", "--yes"], cwd=git_repo).exit_code == 0
    # push's own manifest.lock update must land in its own commit before pull
    # (DESIGN §8.4) so the tree is clean.
    subprocess.run(["git", "add", "-A"], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "push manifest"],
        cwd=git_repo,
        check=True,
        capture_output=True,
    )

    # Drift the automation remotely (simulating a UI edit).
    remote = backend.list_remote("automation")["hall_light_on_motion"]
    backend.update(
        "automation", "hall_light_on_motion", {**remote, "alias": "Hallway light (UI edit)"}
    )

    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code == 0, result.output

    content = (git_repo / "hallway.py").read_text(encoding="utf-8")

    # The drifted object now carries the decorator-form trigger, not when().
    assert "triggers=[state(e.binary_sensor.hall_motion).to(" in content
    assert "when(" not in content
    assert "# --- triggers ---" not in content

    # The result must itself still compile (I3/round-trip sanity).
    from hassle.compiler import compile_bundle

    compiled = compile_bundle(git_repo)
    assert "automation:hall_light_on_motion" in compiled.objects
