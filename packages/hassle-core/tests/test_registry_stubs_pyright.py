"""Pyright actually runs against a sample bundle + the generated stubs, and a
seeded typo produces the expected error.

This is the editor story end-to-end without an editor. No network: pyright
runs fully offline against local files only (it does not fetch anything for
a stdlib-only check like this).

Mechanism: a temp directory containing
  - a `hassle/registry/__init__.pyi` stub file at the same import path pyright
    would resolve `from hassle.registry import entities as e` to, generated
    from `fixtures/registry/home.json`. It must be `__init__.pyi` (not a fake
    `entities.pyi` submodule) because at runtime `entities` is a **module-level
    variable** inside the real `hassle/registry/__init__.py` (an
    `_EntitiesRegistry` instance), not a submodule — a stub submodule file
    would shadow it with a *module* named `entities`, which resolves attribute
    access differently (and does not carry our class-based typing at all).
  - a tiny sample.py using that import with one deliberate typo,
  - a pyrightconfig.json scoping pyright to this temp dir and pointing at the
    real hassle-core src (via extraPaths) so `hassle` itself resolves, while
    letting the local `.pyi` stub win for `hassle.registry` specifically
    (achieved by placing the stub at `<tmp>/typings/hassle/registry/__init__.pyi`
    and setting `stubPath` — pyright prefers a custom stubPath stub over the
    real runtime module for that dotted path).

This test shells out to `pyright` via `uv run pyright` (or the resolved
executable) and asserts the seeded typo is reported.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from hassle.registry.snapshot import RegistrySnapshot
from hassle.registry.stubs import (
    generate_entities_stub,
    generate_hassle_reexport_stub,
    generate_services_stub,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE = REPO_ROOT / "fixtures" / "registry" / "home.json"
CORE_SRC = REPO_ROOT / "packages" / "hassle-core" / "src"


def _pyright_available() -> bool:
    return shutil.which("pyright") is not None or shutil.which("uv") is not None


pytestmark = pytest.mark.skipif(
    not _pyright_available(), reason="pyright/uv not available in this environment"
)


def _run_pyright(cwd: Path) -> subprocess.CompletedProcess[str]:
    # Prefer a directly-available `pyright` executable; fall back to `uv run
    # pyright` from the repo root (uv manages the workspace's pyright install).
    if shutil.which("pyright") is not None:
        cmd = ["pyright", "--outputjson", "."]
        run_cwd = cwd
    else:
        cmd = ["uv", "run", "--project", str(REPO_ROOT), "pyright", "--outputjson", str(cwd)]
        run_cwd = REPO_ROOT
    return subprocess.run(
        cmd,
        cwd=run_cwd,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _setup_typings(tmp_path: Path) -> Path:
    """Build `<tmp>/typings/hassle/registry/__init__.pyi` from the fixture snapshot.

    `entities` must appear as a module-level variable declaration in
    `hassle/registry/__init__.pyi` (matching the real runtime package shape),
    not as a separate `entities.pyi` submodule stub.
    """
    snapshot = RegistrySnapshot.load(FIXTURE)
    stub_text = generate_entities_stub(snapshot)
    typings_dir = tmp_path / "typings" / "hassle" / "registry"
    typings_dir.mkdir(parents=True, exist_ok=True)
    (typings_dir / "__init__.pyi").write_text(stub_text, encoding="utf-8")
    # Package marker so pyright treats `hassle` itself as a regular package.
    (tmp_path / "typings" / "hassle" / "__init__.pyi").write_text("", encoding="utf-8")
    return typings_dir


def _write_pyrightconfig(tmp_path: Path) -> None:
    config = {
        "typeCheckingMode": "basic",
        "stubPath": "typings",
        "extraPaths": [str(CORE_SRC)],
        "reportMissingImports": True,
        "pythonVersion": "3.12",
    }
    (tmp_path / "pyrightconfig.json").write_text(json.dumps(config), encoding="utf-8")


def test_pyright_catches_seeded_entity_typo(tmp_path: Path) -> None:
    _setup_typings(tmp_path)
    _write_pyrightconfig(tmp_path)
    sample = tmp_path / "sample.py"
    sample.write_text(
        "from hassle.registry import entities as e\n"
        "\n"
        "# deliberate typo: 'halway' instead of 'hallway'\n"
        "bad = e.light.halway\n",
        encoding="utf-8",
    )

    proc = _run_pyright(tmp_path)
    payload = json.loads(proc.stdout or "{}")
    diagnostics = payload.get("generalDiagnostics", [])
    messages = " ".join(d.get("message", "") for d in diagnostics)
    assert "halway" in messages or any(
        "sample.py" in d.get("file", "") and d.get("severity") == "error" for d in diagnostics
    ), f"expected a pyright error on the seeded typo; got: {proc.stdout}\n{proc.stderr}"


def test_pyright_accepts_correct_entity_reference(tmp_path: Path) -> None:
    _setup_typings(tmp_path)
    _write_pyrightconfig(tmp_path)
    sample = tmp_path / "sample.py"
    sample.write_text(
        "from hassle.registry import entities as e\ngood = e.light.hallway\n",
        encoding="utf-8",
    )

    proc = _run_pyright(tmp_path)
    payload = json.loads(proc.stdout or "{}")
    diagnostics = payload.get("generalDiagnostics", [])
    errors = [d for d in diagnostics if d.get("severity") == "error"]
    assert errors == [], f"unexpected pyright errors on a correct reference: {errors}"


# ---------------------------------------------------------------------------
# The generated `hassle.services` stub is typo-squiggle effective too. Unlike
# `entities` (a module-level variable
# inside the real `hassle/registry/__init__.py`), `hassle.services` is itself
# a real top-level module at runtime -- so its stub is a plain submodule stub
# file at `typings/hassle/services.pyi` (not nested inside another `.pyi`'s
# `__init__.py`).
# ---------------------------------------------------------------------------


def _setup_services_typings(tmp_path: Path) -> None:
    snapshot = RegistrySnapshot.load(FIXTURE)
    stub_text = generate_services_stub(snapshot)
    hassle_dir = tmp_path / "typings" / "hassle"
    hassle_dir.mkdir(parents=True, exist_ok=True)
    (hassle_dir / "services.pyi").write_text(stub_text, encoding="utf-8")
    if not (hassle_dir / "__init__.pyi").is_file():
        (hassle_dir / "__init__.pyi").write_text("", encoding="utf-8")


def test_pyright_catches_seeded_service_typo(tmp_path: Path) -> None:
    _setup_typings(tmp_path)
    _setup_services_typings(tmp_path)
    _write_pyrightconfig(tmp_path)
    sample = tmp_path / "sample.py"
    sample.write_text(
        "from hassle.services import light\n"
        "\n"
        "# deliberate typo: 'turn_on_light' instead of 'turn_on'\n"
        "light.turn_on_light(brightness_pct=50)\n",
        encoding="utf-8",
    )

    proc = _run_pyright(tmp_path)
    payload = json.loads(proc.stdout or "{}")
    diagnostics = payload.get("generalDiagnostics", [])
    messages = " ".join(d.get("message", "") for d in diagnostics)
    assert "turn_on_light" in messages or any(
        "sample.py" in d.get("file", "") and d.get("severity") == "error" for d in diagnostics
    ), f"expected a pyright error on the seeded service typo; got: {proc.stdout}\n{proc.stderr}"


def test_pyright_accepts_correct_service_call(tmp_path: Path) -> None:
    _setup_typings(tmp_path)
    _setup_services_typings(tmp_path)
    _write_pyrightconfig(tmp_path)
    sample = tmp_path / "sample.py"
    sample.write_text(
        "from hassle.services import light\nlight.turn_on(brightness_pct=50)\n",
        encoding="utf-8",
    )

    proc = _run_pyright(tmp_path)
    payload = json.loads(proc.stdout or "{}")
    diagnostics = payload.get("generalDiagnostics", [])
    errors = [d for d in diagnostics if d.get("severity") == "error"]
    assert errors == [], f"unexpected pyright errors on a correct service call: {errors}"


# ---------------------------------------------------------------------------
# Regression: a `typings/hassle/` dir with ONLY submodule stubs
# (registry/services) and no top-level `typings/hassle/__init__.pyi`
# risks pyright treating `hassle` as a namespace/partial stub package for
# that dotted path, silently hiding the REAL package's own top-level surface
# (`from hassle import *` names). This assertion class must hold with the
# FULL typings tree (entities + services + the reexport stub) present.
# ---------------------------------------------------------------------------


def _setup_full_typings_tree(tmp_path: Path) -> None:
    _setup_typings(tmp_path)
    _setup_services_typings(tmp_path)
    hassle_dir = tmp_path / "typings" / "hassle"
    reexport_stub = generate_hassle_reexport_stub()
    (hassle_dir / "__init__.pyi").write_text(reexport_stub, encoding="utf-8")


def test_star_import_names_are_not_undefined_with_full_typings_tree(tmp_path: Path) -> None:
    _setup_full_typings_tree(tmp_path)
    _write_pyrightconfig(tmp_path)
    sample = tmp_path / "sample.py"
    sample.write_text(
        "from hassle import automation, service, state, Mode\n"
        "\n"
        "@automation(id='x', mode=Mode.RESTART)\n"
        "def x():\n"
        "    service('light.turn_on', target={'entity_id': 'light.hallway'})\n"
        "    _ = state('light.hallway')\n",
        encoding="utf-8",
    )

    proc = _run_pyright(tmp_path)
    payload = json.loads(proc.stdout or "{}")
    diagnostics = payload.get("generalDiagnostics", [])
    undefined = [d for d in diagnostics if d.get("rule") == "reportUndefinedVariable"]
    assert undefined == [], (
        f"expected zero reportUndefinedVariable with the full typings tree present; "
        f"got: {undefined}\n{proc.stdout}\n{proc.stderr}"
    )


def test_generated_typings_tree_itself_is_pyright_clean(tmp_path: Path) -> None:
    """Reviewer finding B2 item (b): the prior pyright integration test only
    ever filtered on `reportUndefinedVariable` in a SAMPLE bundle file,
    never inspected pyright's diagnostics ON the generated `.pyi` files
    themselves -- which is exactly where the B1 bug (`E_`/`PI`/`TAU`
    re-exported from the wrong, non-defining module) actually surfaces:
    `reportAttributeAccessIssue` ("X is unknown import symbol") and
    `reportUnknownVariableType` inside `typings/hassle/__init__.pyi` itself.
    Widened here to check the WHOLE typings tree's own diagnostics, not just
    a downstream sample file's."""
    _setup_full_typings_tree(tmp_path)
    _write_pyrightconfig(tmp_path)
    # A minimal, unrelated sample so pyright has at least one non-stub file
    # to analyze (the config's `.` scope already includes `typings/`).
    (tmp_path / "sample.py").write_text("from hassle import automation\n", encoding="utf-8")

    proc = _run_pyright(tmp_path)
    payload = json.loads(proc.stdout or "{}")
    diagnostics = payload.get("generalDiagnostics", [])
    flagged_rules = {"reportAttributeAccessIssue", "reportUnknownVariableType"}
    stub_diagnostics = [
        d for d in diagnostics if d.get("rule") in flagged_rules and "typings" in d.get("file", "")
    ]
    assert stub_diagnostics == [], (
        f"generated typings tree has pyright diagnostics on itself: {stub_diagnostics}\n"
        f"{proc.stdout}\n{proc.stderr}"
    )


def _write_pyrightconfig_escalating_incomplete_stub(tmp_path: Path) -> None:
    """Same as :func:`_write_pyrightconfig`, but escalates
    ``reportIncompleteStub`` from its default `warning` severity to `error`
    (N1: a bare module-level ``def __getattr__`` in ``hassle/services.pyi``
    trips this rule -- it's a `warning` by default, so the shared config
    above never surfaced it; escalating here proves the generator's targeted
    `# pyright: ignore[reportIncompleteStub]` suppression actually works,
    isolated to this one test so it never masks a REAL incomplete-stub bug
    the rest of this file's tests would otherwise catch)."""
    config = {
        "typeCheckingMode": "basic",
        "stubPath": "typings",
        "extraPaths": [str(CORE_SRC)],
        "reportMissingImports": True,
        "reportIncompleteStub": "error",
        "pythonVersion": "3.12",
    }
    (tmp_path / "pyrightconfig.json").write_text(json.dumps(config), encoding="utf-8")


def test_services_stub_getattr_does_not_trigger_incomplete_stub(tmp_path: Path) -> None:
    _setup_full_typings_tree(tmp_path)
    _write_pyrightconfig_escalating_incomplete_stub(tmp_path)
    sample = tmp_path / "sample.py"
    sample.write_text(
        "from hassle.services import light\nlight.turn_on(brightness_pct=50)\n",
        encoding="utf-8",
    )

    proc = _run_pyright(tmp_path)
    payload = json.loads(proc.stdout or "{}")
    diagnostics = payload.get("generalDiagnostics", [])
    incomplete = [d for d in diagnostics if d.get("rule") == "reportIncompleteStub"]
    assert incomplete == [], (
        f"expected zero reportIncompleteStub with the generated services stub; "
        f"got: {incomplete}\n{proc.stdout}\n{proc.stderr}"
    )
