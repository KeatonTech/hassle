"""Regression (owner field failure, 2026-07-06): the decompiler shells out to
the `ruff` BINARY at runtime to format its output, but resolved it via bare
PATH lookup only. In the dev venv / CI that always works (ruff is a dev
dependency), so nothing caught that a standalone `uv tool install`ed CLI has
ruff inside its own venv bin — which is NOT on PATH — making every
`hassle pull` crash with a raw FileNotFoundError.

Contract pinned here:
1. `_resolve_ruff_executable` prefers the running interpreter's own bin dir
   (`Path(sys.executable).parent / "ruff"`) — the venv/tool-install case —
   then falls back to PATH.
2. When ruff is nowhere, `_format_with_ruff` raises a one-paragraph
   what/where/fix `RuffNotFoundError`, never a raw FileNotFoundError.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from hassle.decompiler.codegen import (
    RuffNotFoundError,
    _format_with_ruff,
    _resolve_ruff_executable,
)


def test_resolver_prefers_interpreter_bin_dir(tmp_path, monkeypatch) -> None:
    fake_bin = tmp_path / "venv-bin"
    fake_bin.mkdir()
    fake_ruff = fake_bin / "ruff"
    fake_ruff.write_text("#!/bin/sh\n")
    fake_ruff.chmod(0o755)
    monkeypatch.setattr(sys, "executable", str(fake_bin / "python"))
    # PATH deliberately empty: the interpreter-bin hit must not depend on it.
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert _resolve_ruff_executable() == str(fake_ruff)


def test_resolver_falls_back_to_path(tmp_path, monkeypatch) -> None:
    path_bin = tmp_path / "path-bin"
    path_bin.mkdir()
    path_ruff = path_bin / "ruff"
    path_ruff.write_text("#!/bin/sh\n")
    path_ruff.chmod(0o755)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "nowhere" / "python"))
    monkeypatch.setenv("PATH", str(path_bin))
    assert _resolve_ruff_executable() == str(path_ruff)


def test_missing_ruff_raises_clean_error(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(sys, "executable", str(tmp_path / "nowhere" / "python"))
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    with pytest.raises(RuffNotFoundError) as excinfo:
        _format_with_ruff("x = 1\n")
    msg = str(excinfo.value)
    assert "ruff" in msg
    assert "Fix:" in msg
    # Never the raw OS error users saw in the field.
    assert "Errno" not in msg


def test_declared_as_runtime_dependency() -> None:
    """ruff must be a REAL dependency of hassle-core, not just dev tooling —
    the decompiler needs the binary at runtime in any install."""
    import tomllib

    pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    deps = tomllib.loads(pyproject)["project"]["dependencies"]
    assert any(d.split(">=")[0].split("==")[0].strip() == "ruff" for d in deps), deps
