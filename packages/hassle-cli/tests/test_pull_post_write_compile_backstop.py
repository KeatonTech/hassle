"""`ux/shared-script-calls-fix` (coordinator task 3): a safety backstop --
after `hassle pull` writes files, recompile the bundle. If it doesn't
actually compile (a decompiler bug -- the exact field failure this fix
branch addresses, or any other coordination bug we haven't found yet),
`hassle pull` must:

- print a what/where/fix error stating this is a Hassle decompiler bug (not
  a user mistake), asking the user to report it, and noting that a
  `--allow-dirty` re-pull after a fix is safe;
- exit nonzero;
- leave the written files in place for diagnosis (never roll back/delete --
  the user needs them to file a useful bug report, and a subsequent fixed
  `hassle pull --allow-dirty` will just overwrite them again).

Two backstops now exist (coordinator task 4 adds the second, cheaper one):

1. A pre-write, adopt-batches-only self-check
   (`hassle.sync.pull_apply._self_check_adopt_batches`,
   `test_pull_adopt_batch_self_check.py`) that fires BEFORE any file is
   written, for a broken ADOPT batch considered in isolation.
2. THIS module's post-write, whole-real-bundle-tree recompile
   (`hassle_cli.cli.pull`), which additionally covers anything the narrower
   pre-write check can't see -- in particular `_refresh`'s single-object
   splice path (see `hassle.sync.pull_apply`'s module docstring for why that
   path isn't pre-write-self-checked).

Simulated here by monkeypatching the decompiler to emit deliberately broken
source for a REFRESH -- this is a backstop for decompiler bugs in general,
not just the one this branch fixes, so the test doesn't rely on a real
broken-bundle shape.
"""

from __future__ import annotations

from pathlib import Path


def test_pull_backstop_catches_noncompiling_refresh_output(
    git_repo: Path, cli, fake_backend, toml_writer, monkeypatch
) -> None:
    # `bundle_dir` (behind `git_repo`) ships `hallway.py` declaring
    # `hall_light_on_motion` (id="hall_light_on_motion"), already tracked as
    # a managed object. Making the backend's remote copy of that SAME object
    # differ triggers REFRESH, exercising `_refresh`'s splice path -- the one
    # the pre-write, adopt-batches-only self-check (task 4) cannot cover.
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)

    import subprocess

    subprocess.run(["git", "add", "-A"], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "point at fake backend"],
        cwd=git_repo,
        check=True,
        capture_output=True,
    )

    # First pull establishes the manifest baseline for hall_light_on_motion
    # (adopts the backend's copy of the object the local bundle already
    # declares, matching it up by id) with a healthy decompiler.
    first = cli(["pull"], cwd=git_repo)
    assert first.exit_code == 0, first.output
    subprocess.run(["git", "add", "-A"], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "baseline"], cwd=git_repo, check=True, capture_output=True
    )

    # Now drift it in "HA" (the backend) so the next pull sees REFRESH.
    backend.update(
        "automation",
        "hall_light_on_motion",
        {
            "id": "hall_light_on_motion",
            "alias": "Hallway light on motion (renamed in the UI)",
            "triggers": [],
            "conditions": [],
            "actions": [],
            "mode": "single",
        },
    )

    from hassle.sync import pull_apply as pull_apply_mod

    def _broken_decompile_bundle(objects, *, script_refs=None):
        return (
            "from hassle import *\n\n"
            "from hassle.registry import entities as e\n\n\n"
            "@automation(id='hall_light_on_motion', alias='x')\n"
            "def hall_light_on_motion():\n"
            "    raise RuntimeError('simulated decompiler coordination bug')\n"
        )

    monkeypatch.setattr(pull_apply_mod, "decompile_bundle", _broken_decompile_bundle)

    result = cli(["pull"], cwd=git_repo)

    assert result.exit_code != 0
    lowered = result.output.lower()
    assert "decompiler" in lowered or "hassle bug" in lowered or "bug" in lowered
    assert "report" in lowered
    assert "--allow-dirty" in result.output

    # The file is left in place for diagnosis -- never rolled back.
    assert (git_repo / "hallway.py").is_file()


def test_pull_backstop_is_silent_when_decompile_output_is_healthy(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    # Sanity check: the backstop must not false-positive on an ordinary,
    # correctly-decompiling pull (already covered indirectly by every other
    # green pull test, but pinned explicitly here since it's the new
    # post-write step this fix adds).
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)

    import subprocess

    subprocess.run(["git", "add", "-A"], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "point at fake backend"],
        cwd=git_repo,
        check=True,
        capture_output=True,
    )

    backend.create(
        "automation",
        {
            "id": "ordinary_automation",
            "alias": "Ordinary automation",
            "triggers": [],
            "conditions": [],
            "actions": [],
            "mode": "single",
        },
    )

    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code == 0, result.output
