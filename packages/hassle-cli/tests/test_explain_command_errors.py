"""`hassle explain <object_key>` with an unknown key previously printed
KeyError's re-quoted repr with no "Fix:" clause -- error messages must
state what/where/fix."""

from __future__ import annotations

from pathlib import Path


def test_explain_unknown_object_key_gives_clean_error(bundle_dir: Path, cli) -> None:
    result = cli(["explain", "automation:does_not_exist"], cwd=bundle_dir)
    assert result.exit_code != 0
    assert "does_not_exist" in result.output
    assert "fix" in result.output.lower()
    # KeyError's own re-quoted repr (`"'...'"`) must not leak through.
    assert "\"'" not in result.output
