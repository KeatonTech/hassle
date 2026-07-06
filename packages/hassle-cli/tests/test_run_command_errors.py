"""M9 error-message audit finding: `hassle run <target>` with a malformed
target (missing `::`) or an unknown automation name previously raised a bare
`ValueError`/`KeyError` with no "Fix:" clause and no clean CLI-level exit
(both propagated as an uncaught traceback -- CliRunner is invoked with
`catch_exceptions=False` in this suite, matching real subprocess behavior,
so an untranslated exception would crash the process). Fixed: both now
degrade to a clean exit code 1 with what/where/fix text (R6).
"""

from __future__ import annotations

from pathlib import Path


def test_run_missing_separator_gives_clean_error(bundle_dir: Path, cli) -> None:
    result = cli(["run", "hallway.py"], cwd=bundle_dir)
    assert result.exit_code != 0
    assert "::" in result.output
    assert "fix" in result.output.lower()


def test_run_unknown_automation_gives_clean_error(bundle_dir: Path, cli) -> None:
    result = cli(["run", "hallway.py::does_not_exist"], cwd=bundle_dir)
    assert result.exit_code != 0
    assert "does_not_exist" in result.output
    assert "fix" in result.output.lower()
