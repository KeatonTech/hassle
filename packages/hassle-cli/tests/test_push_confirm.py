"""`test_push_is_plan_plus_confirm` -- push refuses without confirmation
when deletions are present; `--yes` bypasses.
"""

from __future__ import annotations

from pathlib import Path


def test_push_with_only_creates_does_not_require_confirmation(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    # No deletions, no prompt needed -- exits 0 without --yes and without stdin input.
    result = cli(["push"], cwd=git_repo)
    assert result.exit_code == 0, result.output
    assert "hall_light_on_motion" in backend.list_remote("automation")


def test_push_with_deletion_refuses_without_confirmation(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    assert cli(["push", "--yes"], cwd=git_repo).exit_code == 0

    # Remove the local source -> next plan shows a `delete`.
    (git_repo / "hallway.py").unlink()

    result = cli(["push"], cwd=git_repo, env={})  # no --yes, no piped confirmation
    assert result.exit_code != 0
    assert "delete" in result.output.lower()
    assert "hall_light_on_motion" in backend.list_remote("automation")  # untouched


def test_push_with_deletion_and_yes_flag_applies(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    assert cli(["push", "--yes"], cwd=git_repo).exit_code == 0

    (git_repo / "hallway.py").unlink()

    result = cli(["push", "--yes"], cwd=git_repo)
    assert result.exit_code == 0, result.output
    assert "hall_light_on_motion" not in backend.list_remote("automation")


def test_push_prints_ready_made_commit_message(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    _backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    result = cli(["push", "--yes"], cwd=git_repo)
    assert result.exit_code == 0, result.output
    assert "sync:" in result.output.lower() or "commit" in result.output.lower()


def test_push_surfaces_the_created_identity_divergence_message(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    """Owner duplicate-create report: when HA derives a different helper id
    than the bundle declares, push must SAY so (naming the derived id),
    not just print a FAILED outcome map."""
    _backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    (git_repo / "helpers_misnamed.py").write_text(
        """
from hassle import input_boolean

input_boolean(id="declared_id_that_wont_match", name="Totally Different Name")
""",
        encoding="utf-8",
    )
    result = cli(["push", "--yes"], cwd=git_repo)
    assert result.exit_code != 0
    assert "totally_different_name" in result.output  # the id HA derived
    assert "declared_id_that_wont_match" in result.output
