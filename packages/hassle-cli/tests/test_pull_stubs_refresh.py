"""ux/stub-docstrings item 2: `hassle pull` also regenerates
`typings/hassle/registry/__init__.pyi` write-if-changed from the fresh
registry snapshot, so stubs can never go stale.

Before this change, a bundle that never ran `hassle stubs` by hand (the
owner's real bundle, notably) had NO `typings/` dir at all, even after many
pulls -- pyright/Pylance had zero knowledge of the instance's real entities.
`hassle stubs` stays available for a manual, on-demand refresh (e.g. right
after `login`, before the first `pull`).
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def _commit_all(repo: Path, message: str) -> None:
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", message], cwd=repo, check=True, capture_output=True
    )


def _stub_path(root: Path) -> Path:
    return root / "typings" / "hassle" / "registry" / "__init__.pyi"


def test_pull_writes_stub_when_missing(git_repo: Path, cli, fake_backend, toml_writer) -> None:
    _backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    _commit_all(git_repo, "point at fake backend")
    assert not _stub_path(git_repo).is_file()

    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code == 0, result.output

    stub_path = _stub_path(git_repo)
    assert stub_path.is_file()
    assert "class _EntitiesRegistry" in stub_path.read_text(encoding="utf-8")
    # Package marker so pyright treats the synthetic `hassle` stub package as
    # a regular package (matches `hassle stubs`' own convention).
    assert (git_repo / "typings" / "hassle" / "__init__.pyi").is_file()


def test_pull_prints_step_line_only_when_stub_changes(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    _backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    _commit_all(git_repo, "point at fake backend")

    first = cli(["pull"], cwd=git_repo)
    assert first.exit_code == 0, first.output
    assert "typings" in first.output
    assert "hassle/registry/__init__.pyi" in first.output.replace("\\", "/")

    _commit_all(git_repo, "first pull")

    stub_path = _stub_path(git_repo)
    before = stub_path.read_text(encoding="utf-8")

    second = cli(["pull"], cwd=git_repo)
    assert second.exit_code == 0, second.output
    # Byte-stable: an unchanged registry snapshot must not rewrite the stub,
    # and pull must not print a step line for a no-op stub refresh (matches
    # `_write_registry_snapshot`'s write-if-changed convention).
    assert stub_path.read_text(encoding="utf-8") == before
    assert "typings" not in second.output


def test_pull_stub_is_byte_stable_across_second_pull(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    _backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    _commit_all(git_repo, "point at fake backend")
    assert cli(["pull"], cwd=git_repo).exit_code == 0

    _commit_all(git_repo, "first pull")

    stub_path = _stub_path(git_repo)
    mtime_before = stub_path.stat().st_mtime_ns
    content_before = stub_path.read_text(encoding="utf-8")

    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code == 0, result.output
    assert stub_path.read_text(encoding="utf-8") == content_before
    # write-if-changed: file must not even be re-written (mtime unchanged).
    assert stub_path.stat().st_mtime_ns == mtime_before


def test_hassle_stubs_still_works_for_manual_refresh(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    """`hassle stubs` stays for manual refresh (unchanged command surface)."""
    _backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    _commit_all(git_repo, "point at fake backend")
    assert cli(["pull"], cwd=git_repo).exit_code == 0

    stub_path = _stub_path(git_repo)
    stub_path.unlink()

    result = cli(["stubs"], cwd=git_repo)
    assert result.exit_code == 0, result.output
    assert stub_path.is_file()


def test_pull_stub_matches_registry_snapshot_entities(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    _backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    _commit_all(git_repo, "point at fake backend")
    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code == 0, result.output

    stub_text = _stub_path(git_repo).read_text(encoding="utf-8")
    # Spot-check a known fixture entity is present as a typed attribute.
    assert "hallway: LightEntity" in stub_text


def test_pull_stub_updates_when_registry_snapshot_changes(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    _commit_all(git_repo, "point at fake backend")
    assert cli(["pull"], cwd=git_repo).exit_code == 0

    _commit_all(git_repo, "first pull")

    from hassle.registry.snapshot import EntityInfo

    backend.registry_snapshot = backend.registry_snapshot.model_copy(
        update={
            "entities": [
                *backend.registry_snapshot.entities,
                EntityInfo(entity_id="light.brand_new", name="Brand New Light"),
            ]
        }
    )

    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code == 0, result.output
    assert "typings" in result.output

    stub_text = _stub_path(git_repo).read_text(encoding="utf-8")
    assert "brand_new: LightEntity" in stub_text
