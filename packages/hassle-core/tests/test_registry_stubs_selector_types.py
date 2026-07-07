"""Coordinator-flagged regression: a real HA `get_services` field schema
mostly describes its shape via `selector: {<selector_type>: {...}}`, not a
flat `type:` string (docs/ha-api-notes.md §6). The generated stub must never
emit a bare, unresolvable Python identifier as a type annotation for ANY
selector type it doesn't specifically recognize -- `_field_type` must always
resolve to a real, safe annotation (never a leaked raw selector-type word
like a bare `location`).

Regression-pinned with a `location` selector field (docs/ha-api-notes.md's
own example of a selector-based field with no flat `type`), and proven via a
standalone pyright check over the generated stub content (the class of test
that would have caught this).
"""

from __future__ import annotations

import ast
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from hassle.registry.snapshot import RegistrySnapshot, ServiceDef, ServiceField
from hassle.registry.stubs import _field_type, generate_entities_stub, generate_services_stub

REPO_ROOT = Path(__file__).resolve().parents[3]
CORE_SRC = REPO_ROOT / "packages" / "hassle-core" / "src"


def _snapshot_with_location_selector() -> RegistrySnapshot:
    base = RegistrySnapshot.load(REPO_ROOT / "fixtures" / "registry" / "home.json")
    zone_field = ServiceField(selector={"location": {}})
    services = dict(base.services)
    services["person"] = {
        "goto": ServiceDef(name="Go to", fields={"zone": zone_field}),
    }
    return base.model_copy(update={"services": services})


def test_field_type_never_returns_bare_unmapped_selector_word() -> None:
    # A field with a `selector: {"location": {...}}` shape and no flat `type`
    # must resolve to a real, safe annotation -- not a bare `location`.
    field = ServiceField(selector={"location": {}})
    py_type = _field_type(field.type, selector=field.selector)
    assert py_type != "location"
    # Must be one of the annotations that are always valid without further
    # imports in the generated stub (str, a builtin union, or a qualified
    # typing.Any/dict reference this module's header already provides).
    assert py_type in {"str", "dict[str, Any]", "Any", "dict[str, Any] | str"}


def test_generated_entities_stub_never_contains_bare_location_annotation() -> None:
    snapshot = _snapshot_with_location_selector()
    stub = generate_entities_stub(snapshot)
    ast.parse(stub)  # must always be syntactically valid regardless
    assert "zone: location" not in stub


def test_generated_services_stub_never_contains_bare_location_annotation() -> None:
    snapshot = _snapshot_with_location_selector()
    stub = generate_services_stub(snapshot)
    ast.parse(stub)
    assert "zone: location" not in stub


def _pyright_available() -> bool:
    return shutil.which("pyright") is not None or shutil.which("uv") is not None


@pytest.mark.skipif(not _pyright_available(), reason="pyright/uv not available")
def test_generated_services_stub_with_selector_field_pyright_checks_clean(
    tmp_path: Path,
) -> None:
    """The class of test that would have caught the whole bug: run pyright
    directly over a generated stub containing a selector-typed field, with no
    bundle file involved at all -- the stub itself must be self-consistent."""
    snapshot = _snapshot_with_location_selector()
    stub_text = generate_services_stub(snapshot)
    typings_dir = tmp_path / "typings" / "hassle"
    typings_dir.mkdir(parents=True)
    (typings_dir / "services.pyi").write_text(stub_text, encoding="utf-8")
    (typings_dir / "__init__.pyi").write_text("", encoding="utf-8")
    (tmp_path / "pyrightconfig.json").write_text(
        json.dumps(
            {
                "typeCheckingMode": "basic",
                "stubPath": "typings",
                "extraPaths": [str(CORE_SRC)],
                "pythonVersion": "3.12",
            }
        ),
        encoding="utf-8",
    )

    if shutil.which("pyright") is not None:
        cmd = ["pyright", "--outputjson", "."]
        cwd = tmp_path
    else:
        cmd = ["uv", "run", "--project", str(REPO_ROOT), "pyright", "--outputjson", str(tmp_path)]
        cwd = REPO_ROOT
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=120)
    payload = json.loads(proc.stdout or "{}")
    diagnostics = payload.get("generalDiagnostics", [])
    errors = [d for d in diagnostics if d.get("severity") == "error"]
    assert errors == [], f"generated stub does not pyright-check clean: {errors}"
