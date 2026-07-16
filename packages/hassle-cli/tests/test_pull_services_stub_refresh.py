"""`typings/hassle/services.pyi` is generated alongside the entities stub --
same write path, both `hassle stubs` and `hassle pull`'s auto-refresh emit
it (mirrors `test_pull_stubs_refresh.py`'s entities-stub coverage exactly).
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def _commit_all(repo: Path, message: str) -> None:
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", message], cwd=repo, check=True, capture_output=True
    )


def _services_stub_path(root: Path) -> Path:
    return root / "typings" / "hassle" / "services.pyi"


def test_pull_writes_services_stub_when_missing(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    _backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    _commit_all(git_repo, "point at fake backend")
    assert not _services_stub_path(git_repo).is_file()

    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code == 0, result.output

    stub_path = _services_stub_path(git_repo)
    assert stub_path.is_file()
    assert "class _LightServices" in stub_path.read_text(encoding="utf-8")


def test_pull_services_stub_byte_stable_across_second_pull(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    _backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    _commit_all(git_repo, "point at fake backend")
    assert cli(["pull"], cwd=git_repo).exit_code == 0

    _commit_all(git_repo, "first pull")

    stub_path = _services_stub_path(git_repo)
    mtime_before = stub_path.stat().st_mtime_ns
    content_before = stub_path.read_text(encoding="utf-8")

    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code == 0, result.output
    assert stub_path.read_text(encoding="utf-8") == content_before
    assert stub_path.stat().st_mtime_ns == mtime_before


def test_hassle_stubs_command_writes_services_stub(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    """`hassle stubs` (manual refresh) writes BOTH stubs, same command."""
    _backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    _commit_all(git_repo, "point at fake backend")
    assert cli(["pull"], cwd=git_repo).exit_code == 0

    stub_path = _services_stub_path(git_repo)
    stub_path.unlink()

    result = cli(["stubs"], cwd=git_repo)
    assert result.exit_code == 0, result.output
    assert stub_path.is_file()


def _reexport_stub_path(root: Path) -> Path:
    return root / "typings" / "hassle" / "__init__.pyi"


def test_pull_writes_hassle_reexport_stub(git_repo: Path, cli, fake_backend, toml_writer) -> None:
    """Coordinator hardening: `typings/hassle/__init__.pyi` (the top-level
    re-export guarding against pyright treating `hassle` as a namespace/
    partial stub package once submodule stubs exist for it) is written
    alongside the entities/services stubs, non-empty, with real content."""
    _backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    _commit_all(git_repo, "point at fake backend")

    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code == 0, result.output

    stub_path = _reexport_stub_path(git_repo)
    assert stub_path.is_file()
    stub_text = stub_path.read_text(encoding="utf-8")
    assert "automation as automation" in stub_text
    assert "service as service" in stub_text
