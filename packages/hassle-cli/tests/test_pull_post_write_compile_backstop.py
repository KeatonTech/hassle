"""`ux/shared-script-calls-fix` (coordinator task 3): a safety backstop --
after `hassle pull` writes files, recompile the bundle. If the freshly
decompiled bundle doesn't actually compile (a decompiler bug -- the exact
field failure this fix branch addresses, or any other coordination bug we
haven't found yet), `hassle pull` must:

- print a what/where/fix error naming the offending file and stating this is
  a Hassle decompiler bug (not a user mistake), asking the user to report it,
  and noting that a `--allow-dirty` re-pull after a fix is safe;
- exit nonzero;
- leave the written files in place for diagnosis (never roll back/delete --
  the user needs them to file a useful bug report, and a subsequent fixed
  `hassle pull --allow-dirty` will just overwrite them again).

Simulated here by monkeypatching the decompiler to emit deliberately broken
source -- this is a backstop for decompiler bugs in general, not just the one
this branch fixes, so the test doesn't rely on a real broken-bundle shape.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def _commit_toml_change(bundle: Path) -> None:
    subprocess.run(["git", "add", "-A"], cwd=bundle, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "point at fake backend"],
        cwd=bundle,
        check=True,
        capture_output=True,
    )


def test_pull_backstop_catches_noncompiling_decompile_output(
    git_repo: Path, cli, fake_backend, toml_writer, monkeypatch
) -> None:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    _commit_toml_change(git_repo)

    backend.create(
        "automation",
        {
            "id": "broken_by_decompiler_bug",
            "alias": "Broken by decompiler bug",
            "triggers": [],
            "conditions": [],
            "actions": [],
            "mode": "single",
        },
    )

    # Simulate a decompiler coordination bug: whatever object set it's given,
    # emit source that raises at compile time (a bare `raise` statement is
    # the simplest "definitely does not compile" body imaginable).
    import hassle_cli.pull_apply as pull_apply_mod

    def _broken_decompile_bundle(objects, *, script_refs=None):
        return (
            "from hassle import *\n\n"
            "from hassle.registry import entities as e\n\n\n"
            "@automation(id='broken_by_decompiler_bug', alias='x')\n"
            "def broken_by_decompiler_bug():\n"
            "    raise RuntimeError('simulated decompiler coordination bug')\n"
        )

    monkeypatch.setattr(pull_apply_mod, "decompile_bundle", _broken_decompile_bundle)

    result = cli(["pull"], cwd=git_repo)

    assert result.exit_code != 0
    lowered = result.output.lower()
    assert "decompiler" in lowered or "hassle bug" in lowered or "bug" in lowered
    assert "report" in lowered
    assert "--allow-dirty" in result.output

    # Files are left in place for diagnosis -- never rolled back.
    written = list((git_repo / "automations").glob("*.py"))
    assert any("broken_by_decompiler_bug" in p.read_text(encoding="utf-8") for p in written), (
        "the written (broken) file must be left in place for the user to diagnose/report"
    )


def test_pull_backstop_is_silent_when_decompile_output_is_healthy(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    # Sanity check: the backstop must not false-positive on an ordinary,
    # correctly-decompiling pull (already covered indirectly by every other
    # green pull test, but pinned explicitly here since it's the new
    # post-write step this fix adds).
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    _commit_toml_change(git_repo)

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
