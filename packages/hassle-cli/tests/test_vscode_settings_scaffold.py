"""`hassle init` (and `hassle pull`, when it scaffolds directories a bundle
predating this change never had) writes `.vscode/settings.json` pointing
pyright/Pylance at the stub location that actually makes
autocompletion/typo-squiggles work with zero configuration (DESIGN §11
layer 1).

The layout that matters (verified against a *real* pyright run, not asserted
by convention -- see `packages/hassle-core/tests/test_registry_stubs_pyright.py`
and its extended sibling `test_registry_stubs_pyright_init_template.py`):
pyright only prefers a stub over a real runtime module when the stub sits
under a directory named by `python.analysis.stubPath` (VS Code/Pylance's
setting; bare pyright's equivalent is `pyrightconfig.json`'s `stubPath`), at
the dotted-import-mirroring path `<stubPath>/hassle/registry/__init__.pyi`.
`hassle stubs` (see `test_cli_commands.py::test_stubs_generates_pyi_files`)
writes exactly there (`typings/hassle/registry/__init__.pyi`), so `init`'s
`.vscode/settings.json` must set `python.analysis.stubPath` to `"typings"`.
"""

from __future__ import annotations

import json
from pathlib import Path

from hassle_cli.init_cmd import init_bundle


def test_init_writes_vscode_settings(tmp_path: Path) -> None:
    init_bundle(tmp_path)
    settings_path = tmp_path / ".vscode" / "settings.json"
    assert settings_path.is_file()


def test_vscode_settings_stub_path_matches_where_stubs_are_written(tmp_path: Path) -> None:
    # The load-bearing assertion: `python.analysis.stubPath` must literally be
    # the directory `hassle stubs` writes into (`typings/`), or pyright/Pylance
    # never finds the generated types.
    init_bundle(tmp_path)
    settings = json.loads((tmp_path / ".vscode" / "settings.json").read_text(encoding="utf-8"))
    assert settings["python.analysis.stubPath"] == "typings"


def test_vscode_settings_extra_paths_includes_bundle_root(tmp_path: Path) -> None:
    # Cross-file imports (`from lib.x import y`, `from helpers.modes import
    # guest_mode`) are PEP 420 namespace packages rooted at the bundle root
    # (DESIGN §6, docs/ha-api-notes.md §17.9) -- Pylance needs the bundle root
    # on its analysis path to resolve them the same way the compiler's loader
    # does (`sys.path` insertion at compile time).
    init_bundle(tmp_path)
    settings = json.loads((tmp_path / ".vscode" / "settings.json").read_text(encoding="utf-8"))
    extra_paths = settings["python.analysis.extraPaths"]
    assert "." in extra_paths


def test_vscode_settings_does_not_overwrite_existing_file(tmp_path: Path) -> None:
    init_bundle(tmp_path)
    custom = json.dumps({"my.custom.setting": True})
    (tmp_path / ".vscode" / "settings.json").write_text(custom, encoding="utf-8")

    init_bundle(tmp_path)  # re-run, idempotent

    assert (tmp_path / ".vscode" / "settings.json").read_text(encoding="utf-8") == custom


def test_pull_writes_vscode_settings_when_scaffolding(
    bundle_dir: Path, cli, fake_backend, toml_writer
) -> None:
    # Same idempotent-scaffold contract as lib/README.md (test_lib_readme_scaffold.py):
    # a hand-rolled bundle fixture predating `hassle init`'s `.vscode/` write
    # still gets it on its first `pull`.
    assert not (bundle_dir / ".vscode").exists()
    _backend, token = fake_backend
    toml_writer(bundle_dir, backend_token=token)

    result = cli(["pull"], cwd=bundle_dir)

    assert result.exit_code == 0, result.output
    assert (bundle_dir / ".vscode" / "settings.json").is_file()


def test_settings_default_interpreter_points_at_bundle_venv(tmp_path) -> None:
    """Regression: with the bundle's uv-project scaffold in place, VS Code's
    Python extension could sit on an interpreter with no `hassle` installed
    -- every `from hassle import *` name squiggled as undefined while the
    (interpreter-independent) entity stubs still resolved. The generated
    settings must default the interpreter to the bundle's own venv so a
    fresh checkout works with zero clicks."""
    import json

    from hassle_cli.init_cmd import scaffold_vscode_settings

    scaffold_vscode_settings(tmp_path)
    settings = json.loads((tmp_path / ".vscode" / "settings.json").read_text())
    assert settings["python.defaultInterpreterPath"] == "${workspaceFolder}/.venv/bin/python"
