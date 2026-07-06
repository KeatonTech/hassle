"""M8 test 1 (milestone text: "Layer-1 proof (already in M3 CI, extend): fresh
pulled bundle opened cold -> pyright finds a seeded entity typo with zero
configuration").

`test_registry_stubs_pyright.py` proves the *mechanism* works (a hand-built
`typings/hassle/registry/__init__.pyi` + hand-built `pyrightconfig.json`).
This file proves the *product* works: it runs pyright against precisely the
files `hassle init` + `hassle stubs` write to a real bundle directory --
`.vscode/settings.json` (Pylance's `python.analysis.stubPath`/`extraPaths`,
which bare `pyright` also honors when invoked from VS Code's Python extension,
but a standalone `pyright` CLI run needs the equivalent `pyrightconfig.json`;
we write both here to cover "opened cold" in either context) plus the
generated `typings/hassle/registry/__init__.pyi` -- with zero hand-authored
pyright configuration beyond what `hassle init` itself produces.

No network: pyright runs fully offline; `hassle stubs`/`hassle init` are pure
filesystem operations against the local fixture registry snapshot.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from hassle.registry.snapshot import RegistrySnapshot
from hassle.registry.stubs import generate_entities_stub

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE = REPO_ROOT / "fixtures" / "registry" / "home.json"
CORE_SRC = REPO_ROOT / "packages" / "hassle-core" / "src"


def _pyright_available() -> bool:
    return shutil.which("pyright") is not None or shutil.which("uv") is not None


pytestmark = pytest.mark.skipif(
    not _pyright_available(), reason="pyright/uv not available in this environment"
)


def _run_pyright(cwd: Path) -> subprocess.CompletedProcess[str]:
    if shutil.which("pyright") is not None:
        cmd = ["pyright", "--outputjson", "."]
        run_cwd = cwd
    else:
        cmd = ["uv", "run", "--project", str(REPO_ROOT), "pyright", "--outputjson", str(cwd)]
        run_cwd = REPO_ROOT
    return subprocess.run(cmd, cwd=run_cwd, capture_output=True, text=True, timeout=120)


def _build_real_bundle(tmp_path: Path) -> Path:
    """Scaffold via the real `hassle init` + `hassle stubs` code paths (not a
    hand-rolled fixture) -- this is the whole point of the "verify, don't
    build" instruction: assert against what the CLI actually emits."""
    from hassle_cli.init_cmd import init_bundle

    root = tmp_path / "my-house"
    root.mkdir()
    init_bundle(root)

    snapshot = RegistrySnapshot.load(FIXTURE)
    stub_text = generate_entities_stub(snapshot)
    typings_dir = root / "typings" / "hassle" / "registry"
    typings_dir.mkdir(parents=True, exist_ok=True)
    (typings_dir / "__init__.pyi").write_text(stub_text, encoding="utf-8")
    (root / "typings" / "hassle" / "__init__.pyi").write_text("", encoding="utf-8")

    # `python.analysis.stubPath`/`extraPaths` (Pylance) aren't read by a
    # standalone `pyright` CLI invocation -- it needs `pyrightconfig.json`.
    # A real editor's Pylance reads `.vscode/settings.json` directly; this
    # extra file only exists so this test can exercise the *bare pyright*
    # path too (CI has no VS Code/Pylance to drive). Both must agree with
    # what `.vscode/settings.json` says, which the settings-schema test in
    # `packages/hassle-cli/tests/test_vscode_settings_scaffold.py` locks down.
    settings = json.loads((root / ".vscode" / "settings.json").read_text(encoding="utf-8"))
    config = {
        "typeCheckingMode": "basic",
        "stubPath": settings["python.analysis.stubPath"],
        "extraPaths": [str(CORE_SRC)],
        "reportMissingImports": True,
        "pythonVersion": "3.12",
    }
    (root / "pyrightconfig.json").write_text(json.dumps(config), encoding="utf-8")
    return root


def test_fresh_bundle_from_init_catches_seeded_entity_typo(tmp_path: Path) -> None:
    root = _build_real_bundle(tmp_path)
    (root / "sample.py").write_text(
        "from hassle.registry import entities as e\n"
        "\n"
        "# deliberate typo: 'halway' instead of 'hallway'\n"
        "bad = e.light.halway\n",
        encoding="utf-8",
    )

    proc = _run_pyright(root)
    payload = json.loads(proc.stdout or "{}")
    diagnostics = payload.get("generalDiagnostics", [])
    messages = " ".join(d.get("message", "") for d in diagnostics)
    assert "halway" in messages or any(
        "sample.py" in d.get("file", "") and d.get("severity") == "error" for d in diagnostics
    ), f"expected a pyright error on the seeded typo; got: {proc.stdout}\n{proc.stderr}"


def test_fresh_bundle_from_init_accepts_correct_entity_reference(tmp_path: Path) -> None:
    root = _build_real_bundle(tmp_path)
    (root / "sample.py").write_text(
        "from hassle.registry import entities as e\ngood = e.light.hallway\n",
        encoding="utf-8",
    )

    proc = _run_pyright(root)
    payload = json.loads(proc.stdout or "{}")
    diagnostics = payload.get("generalDiagnostics", [])
    errors = [d for d in diagnostics if d.get("severity") == "error"]
    assert errors == [], f"unexpected pyright errors on a correct reference: {errors}"
