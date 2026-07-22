"""`typings/` (derived, regenerated every pull) and `.venv/` (the bundle uv
project's venv) must be gitignored by the scaffold -- a naive `git add -A`
in a fresh bundle was about to commit both."""

from __future__ import annotations

from pathlib import Path

from hassle_cli.git_support import write_gitignore


def test_scaffolded_gitignore_excludes_derived_artifacts(tmp_path: Path) -> None:
    write_gitignore(tmp_path)
    content = (tmp_path / ".gitignore").read_text()
    assert "typings/" in content
    assert ".venv/" in content
    # The offline base stays committed -- only its .bak is ignored.
    assert ".hassle/registry.json.bak" in content
    assert "\n.hassle/registry.json\n" not in content
