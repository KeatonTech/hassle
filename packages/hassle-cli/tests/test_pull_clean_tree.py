"""MILESTONES M7 test 3: `test_pull_requires_clean_tree` -- dirty repo -> refusal
with guidance; `--allow-dirty` works; non-git directory -> one-time warning,
still functions.
"""

from __future__ import annotations

from pathlib import Path


def _tree_bytes(root: Path) -> dict[str, bytes]:
    """Every file under `root` (excluding `.git/` internals), path -> raw bytes."""
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and ".git" not in p.parts
    }


def test_pull_on_dirty_tree_writes_nothing(git_repo: Path, cli, fake_backend, toml_writer) -> None:
    """Regression lock for the 2026-07-13 field report (BrandtCamp bundle):
    `hassle pull` on a dirty tree reportedly emitted the clean-tree refusal
    only AFTER rewriting bundle files (decompiled sources, the registry
    snapshot, typings stubs, docs/DSL.md) -- tangling exactly what the guard
    promises to prevent. The clean-tree check must run before ALL of pull's
    writes: a dirty tree + `pull` must leave every bundle file byte-identical.

    The fixture is arranged so that every write pull could perform is a REAL
    one if the ordering ever regresses: the on-disk registry snapshot is stale
    (refresh would rewrite it, and the typings stubs with it), the bundle has
    no `lib/README.md`/`AGENTS.md`/`docs/`/`pyproject.toml`/`.vscode/`
    (scaffolds would create them), and the backend holds a remote-only
    automation (the plan would ADOPT it into a new source file).
    """
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    # Stale registry snapshot on disk: pull's refresh-on-every-pull (DESIGN
    # §9.2) would rewrite it -- and regenerate the typings stubs -- if it ran.
    (git_repo / ".hassle" / "registry.json").write_text(
        '{"entities": [], "services": {}}\n', encoding="utf-8"
    )
    # A remote-only automation: the plan would ADOPT it (a new source file).
    backend.create(
        "automation",
        {
            "id": "1770000000001",
            "alias": "UI-made automation",
            "triggers": [{"trigger": "state", "entity_id": "binary_sensor.door", "to": "on"}],
            "conditions": [],
            "actions": [{"action": "light.turn_on", "target": {"entity_id": "light.hall"}}],
            "mode": "single",
        },
    )
    import subprocess

    subprocess.run(["git", "add", "-A"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-qm", "baseline"], cwd=git_repo, check=True)

    # The user's in-progress edit -- the ONLY dirt in the tree.
    wip = (git_repo / "hallway.py").read_text(encoding="utf-8") + "# WIP: in-progress edit\n"
    (git_repo / "hallway.py").write_text(wip, encoding="utf-8")

    before = _tree_bytes(git_repo)
    result = cli(["pull"], cwd=git_repo)
    after = _tree_bytes(git_repo)

    assert result.exit_code != 0
    assert "clean" in result.output.lower()
    changed = sorted(
        set(before) ^ set(after) | {path for path in before if after.get(path) != before[path]}
    )
    assert changed == [], (
        "pull on a dirty tree touched bundle files before (or despite) the clean-tree "
        f"refusal: {changed}"
    )


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

    _backend, _token = fake_backend
    outer = tmp_path / "outer_project"
    outer.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=outer, check=True)
    bundle = outer / "home-bundle"
    bundle.mkdir()

    result = cli(["init"], cwd=bundle)
    assert result.exit_code == 0, result.output
    assert not (bundle / ".git").exists()
    assert "enclosing" in result.output.lower() or "nested" in result.output.lower()
