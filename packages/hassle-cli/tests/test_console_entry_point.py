"""The `hassle` console script's own behavior (`hassle_cli.__main__:main`).

The entry point runs click with ``standalone_mode=False`` so it can control
its own exit codes, which means click no longer renders usage errors itself --
these tests pin that the wrapper does it instead, rather than letting a
traceback reach the user for something as ordinary as a mistyped flag.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from hassle_cli.__main__ import main


def _run(argv: list[str]) -> tuple[int, str, str]:
    """Invoke the entry point in-process with a patched argv."""
    import contextlib
    import io
    from unittest.mock import patch

    out, err = io.StringIO(), io.StringIO()
    with (
        patch.object(sys, "argv", ["hassle", *argv]),
        contextlib.redirect_stdout(out),
        contextlib.redirect_stderr(err),
    ):
        try:
            code = main()
        except SystemExit as exc:  # click may still exit for --help/--version
            code = int(exc.code or 0)
    return code, out.getvalue(), err.getvalue()


def test_version_flag_reports_the_installed_version() -> None:
    code, out, _err = _run(["--version"])
    assert code == 0
    assert "hassle" in out.lower()
    # A real version, not a placeholder.
    assert "0.0.0" not in out
    assert any(ch.isdigit() for ch in out)


def test_unknown_option_prints_a_usage_error_not_a_traceback() -> None:
    code, out, err = _run(["--flibbertigibbet"])
    combined = out + err
    assert code == 2, "click reserves exit code 2 for usage errors"
    assert "Traceback" not in combined
    assert "no such option" in combined.lower()


def test_unknown_subcommand_prints_a_usage_error_not_a_traceback() -> None:
    code, out, err = _run(["pul"])
    combined = out + err
    assert code == 2
    assert "Traceback" not in combined
    assert "no such command" in combined.lower()


def test_missing_required_option_prints_a_usage_error_not_a_traceback() -> None:
    code, out, err = _run(["login"])  # --url/--token are required
    combined = out + err
    assert code == 2
    assert "Traceback" not in combined
    assert "missing option" in combined.lower()


def test_help_exits_zero() -> None:
    code, out, _err = _run(["--help"])
    assert code == 0
    assert "Usage:" in out


@pytest.mark.parametrize("argv", [["--flibbertigibbet"], ["pul"]])
def test_usage_errors_are_clean_in_a_real_subprocess(argv: list[str]) -> None:
    """Belt-and-braces: the installed console script, not just the function."""
    proc = subprocess.run(
        [sys.executable, "-m", "hassle_cli", *argv],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert "Traceback" not in (proc.stdout + proc.stderr)
