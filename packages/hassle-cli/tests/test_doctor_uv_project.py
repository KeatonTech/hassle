"""`hassle doctor` reports the bundle's uv-project scaffold status -- three
offline, filesystem-only checks (no `uv`/subprocess spawned by the check
itself): pyproject present? sources path resolves? summary note.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def test_doctor_reports_missing_pyproject(bundle_dir: Path, cli) -> None:
    assert not (bundle_dir / "pyproject.toml").exists()
    result = cli(["doctor"], cwd=bundle_dir)
    assert result.exit_code == 0, result.output
    assert "pyproject.toml" in result.output
    assert "no pyproject.toml" in result.output.lower()


def test_doctor_reports_resolving_sources_path(bundle_dir: Path, cli, tmp_path: Path) -> None:
    toolchain_cli_dir = tmp_path / "checkout" / "packages" / "hassle-cli"
    toolchain_cli_dir.mkdir(parents=True)
    (bundle_dir / "pyproject.toml").write_text(
        "[project]\n"
        'name = "my-house"\n'
        'version = "0.0.0"\n'
        'requires-python = ">=3.12"\n'
        'dependencies = ["hassle-cli"]\n\n'
        "[tool.uv.sources]\n"
        f'hassle-cli = {{ path = "{toolchain_cli_dir.as_posix()}", editable = true }}\n',
        encoding="utf-8",
    )

    result = cli(["doctor"], cwd=bundle_dir)

    assert result.exit_code == 0, result.output
    assert "pyproject.toml" in result.output
    assert "resolves" in result.output.lower()


def test_doctor_reports_stale_sources_path(bundle_dir: Path, cli, tmp_path: Path) -> None:
    stale_path = tmp_path / "does-not-exist" / "packages" / "hassle-cli"
    (bundle_dir / "pyproject.toml").write_text(
        "[project]\n"
        'name = "my-house"\n'
        'dependencies = ["hassle-cli"]\n\n'
        "[tool.uv.sources]\n"
        f'hassle-cli = {{ path = "{stale_path.as_posix()}", editable = true }}\n',
        encoding="utf-8",
    )

    result = cli(["doctor"], cwd=bundle_dir)

    assert result.exit_code == 0, result.output
    assert "does not resolve" in result.output.lower() or "stale" in result.output.lower()


def test_doctor_reports_bare_dependency_shape(bundle_dir: Path, cli) -> None:
    (bundle_dir / "pyproject.toml").write_text(
        '[project]\nname = "my-house"\ndependencies = ["hassle-cli"]\n', encoding="utf-8"
    )

    result = cli(["doctor"], cwd=bundle_dir)

    assert result.exit_code == 0, result.output
    assert "pyproject.toml" in result.output
    assert "no [tool.uv.sources]" in result.output.lower() or "bare" in result.output.lower()


def test_doctor_uv_project_check_never_spawns_a_subprocess(
    bundle_dir: Path, cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Binding: the doctor check is filesystem-only -- it must not spawn a
    real `uv` process to determine the report line, even though the text it
    prints mentions `uv run hassle`."""

    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("hassle doctor must not spawn a subprocess for the uv-project check")

    # `hassle_cli.git_support` legitimately shells out (git checks) -- only
    # forbid the uv_project module's own (nonexistent) subprocess usage by
    # patching the global subprocess entry points and confirming doctor still
    # succeeds without hitting them for anything this check would need. Git
    # itself may still run (bundle_dir isn't a repo here, so is_git_repo's
    # `git` invocation is allowed to fail/return non-git-repo -- it doesn't
    # touch OUR forbidden guard because that guard only fires if code tries
    # to invoke `uv` specifically).
    orig_run = subprocess.run

    def _guarded_run(cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
        if cmd and "uv" in str(cmd[0]):
            _forbidden()
        return orig_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", _guarded_run)

    result = cli(["doctor"], cwd=bundle_dir)
    assert result.exit_code == 0, result.output
