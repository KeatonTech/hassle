"""M18 milestone test 5 — the `hassle.services` stub generator.

Generated alongside the entities stub (same write path, `hassle stubs` and
`hassle pull`'s auto-refresh both emit it): per-domain classes, typed kwargs
from `snapshot.services`, reusing `_service_method`'s field typing. Golden-
tests the generated content against `fixtures/registry/home.json`.
"""

from __future__ import annotations

import ast
import os
import subprocess
from pathlib import Path

import pytest

from hassle.registry.snapshot import RegistrySnapshot
from hassle.registry.stubs import generate_services_stub

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE = REPO_ROOT / "fixtures" / "registry" / "home.json"
GOLDEN = Path(__file__).resolve().parent / "snapshots" / "stubs" / "services.pyi"


@pytest.fixture(scope="module")
def snapshot() -> RegistrySnapshot:
    return RegistrySnapshot.load(FIXTURE)


def _check_golden(actual: str) -> None:
    if os.environ.get("HASSLE_UPDATE_SNAPSHOTS"):
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(actual, encoding="utf-8")
    assert GOLDEN.is_file(), f"missing golden {GOLDEN}; set HASSLE_UPDATE_SNAPSHOTS=1 to write it"
    assert actual == GOLDEN.read_text(encoding="utf-8")


def test_services_stub_golden_matches(snapshot: RegistrySnapshot) -> None:
    actual = generate_services_stub(snapshot)
    _check_golden(actual)


def test_services_stub_contains_domain_module_attr(snapshot: RegistrySnapshot) -> None:
    stub = generate_services_stub(snapshot)
    assert "light: " in stub or "light:" in stub


def test_services_stub_contains_typed_service_method(snapshot: RegistrySnapshot) -> None:
    stub = generate_services_stub(snapshot)
    assert "def turn_on(" in stub
    assert "brightness_pct" in stub


def test_services_stub_module_getattr_present(snapshot: RegistrySnapshot) -> None:
    """The module-level `__getattr__` PEP 562 fallback must ALSO be typed (so
    an unlisted/future domain doesn't become a hard pyright error) -- matches
    the entities stub's own `_EntitiesRegistry.__getattr__` fallback pattern."""
    stub = generate_services_stub(snapshot)
    assert "def __getattr__(" in stub


def test_services_stub_is_valid_python(snapshot: RegistrySnapshot) -> None:
    stub = generate_services_stub(snapshot)
    ast.parse(stub)


def test_services_stub_is_ruff_format_clean(snapshot: RegistrySnapshot, tmp_path: Path) -> None:
    stub = generate_services_stub(snapshot)
    stub_path = tmp_path / "services.pyi"
    stub_path.write_text(stub, encoding="utf-8")
    proc = subprocess.run(
        ["ruff", "format", "--check", str(stub_path)],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 127 or "not found" in (proc.stderr or "").lower():
        pytest.skip("ruff not available in this environment")
    assert proc.returncode == 0, f"ruff format --check failed:\n{proc.stdout}\n{proc.stderr}"
