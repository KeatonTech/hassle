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
    (git_repo / "hallway.py").write_text("# dirty\n", encoding="utf-8")

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


def _make_nested_bundle(tmp_path: Path, toml_writer, token: str) -> tuple[Path, Path]:
    """An outer git repo with the bundle in a subdirectory (a bundle nested in
    an unrelated project repo -- the smoke-test-day regression shape)."""
    import subprocess

    outer = tmp_path / "outer_project"
    outer.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=outer, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=outer, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=outer, check=True)
    bundle = outer / "home-bundle"
    bundle.mkdir()
    toml_writer(bundle, backend_token=token)
    subprocess.run(["git", "add", "-A"], cwd=outer, check=True)
    subprocess.run(["git", "commit", "-qm", "scaffold"], cwd=outer, check=True)
    return outer, bundle


def test_pull_ignores_dirt_outside_nested_bundle(
    tmp_path: Path, cli, fake_backend, toml_writer
) -> None:
    # Uncommitted changes in the ENCLOSING repo, outside the bundle subtree,
    # must not block pull: the clean-tree contract (DESIGN §8.4) is about the
    # bundle's own files landing as their own commit, not the host project's.
    _backend, token = fake_backend
    outer, bundle = _make_nested_bundle(tmp_path, toml_writer, token)
    (outer / "unrelated.txt").write_text("dirty outer work\n", encoding="utf-8")

    result = cli(["pull"], cwd=bundle)
    assert result.exit_code == 0, result.output


def test_pull_refuses_on_dirt_inside_nested_bundle(
    tmp_path: Path, cli, fake_backend, toml_writer
) -> None:
    _backend, token = fake_backend
    _outer, bundle = _make_nested_bundle(tmp_path, toml_writer, token)
    (bundle / "scratch.py").write_text("# in-bundle dirt\n", encoding="utf-8")

    result = cli(["pull"], cwd=bundle)
    assert result.exit_code != 0
    assert "--allow-dirty" in result.output


def test_init_notes_enclosing_repo_when_nested(
    tmp_path: Path, cli, fake_backend, toml_writer
) -> None:
    # init inside a foreign repo must not create a nested repo (already true)
    # AND must tell the user their bundle rides the enclosing repo.
    import subprocess

    _backend, token = fake_backend
    outer = tmp_path / "outer_project"
    outer.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=outer, check=True)
    bundle = outer / "home-bundle"
    bundle.mkdir()

    result = cli(["init"], cwd=bundle)
    assert result.exit_code == 0, result.output
    assert not (bundle / ".git").exists()
    assert "enclosing" in result.output.lower() or "nested" in result.output.lower()
