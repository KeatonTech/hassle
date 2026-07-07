"""M3 milestone test 5 (the big one): pyright actually runs against a sample
bundle + the generated stubs, and a seeded typo produces the expected error.

"This is explicitly the editor story end-to-end without an editor" — the
milestone brief. No network: pyright runs fully offline against local files
only (it does not fetch anything for a stdlib-only check like this).

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
from hassle.registry.stubs import generate_entities_stub, generate_services_stub

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
# M18 test 5 extension: the generated `hassle.services` stub is
# typo-squiggle effective too. Unlike `entities` (a module-level variable
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
