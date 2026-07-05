"""MILESTONES M7 test 3: `test_pull_requires_clean_tree` -- dirty repo -> refusal
with guidance; `--allow-dirty` works; non-git directory -> one-time warning,
still functions.
"""

from __future__ import annotations

from pathlib import Path


def test_pull_refuses_on_dirty_tree(git_repo: Path, cli, fake_backend, toml_writer) -> None:
    _backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    # Dirty the tree (uncommitted change).
    (git_repo / "automations" / "hallway.py").write_text("# dirty\n", encoding="utf-8")

    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code != 0
    assert "clean" in result.output.lower() or "dirty" in result.output.lower()
    assert "--allow-dirty" in result.output


def test_pull_allow_dirty_overrides(git_repo: Path, cli, fake_backend, toml_writer) -> None:
    _backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    assert cli(["push", "--yes"], cwd=git_repo).exit_code == 0

    (git_repo / "README.md").write_text("dirty but unrelated\n", encoding="utf-8")

    result = cli(["pull", "--allow-dirty"], cwd=git_repo)
    assert result.exit_code == 0, result.output


def test_pull_in_non_git_directory_warns_once_but_functions(
    bundle_dir: Path, cli, fake_backend, toml_writer
) -> None:
    _backend, token = fake_backend
    toml_writer(bundle_dir, backend_token=token)
    result = cli(["pull"], cwd=bundle_dir)
    assert result.exit_code == 0, result.output
    assert "git" in result.output.lower()
