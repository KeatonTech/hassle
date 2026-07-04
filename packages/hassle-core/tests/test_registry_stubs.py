"""M3 milestone test 5: `.pyi` stub generator (entities + typed service methods).

Golden-tests the generated stub content against `fixtures/registry/home.json`
byte-for-byte (a plain pytest-managed golden comparison, regenerated only via
`HASSLE_UPDATE_SNAPSHOTS=1`, mirroring the errors-snapshot pattern).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from hassle.registry.snapshot import RegistrySnapshot
from hassle.registry.stubs import generate_entities_stub

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE = REPO_ROOT / "fixtures" / "registry" / "home.json"
GOLDEN = Path(__file__).resolve().parent / "snapshots" / "stubs" / "entities.pyi"


@pytest.fixture(scope="module")
def snapshot() -> RegistrySnapshot:
    return RegistrySnapshot.load(FIXTURE)


def _check_golden(actual: str) -> None:
    if os.environ.get("HASSLE_UPDATE_SNAPSHOTS"):
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(actual, encoding="utf-8")
    assert GOLDEN.is_file(), f"missing golden {GOLDEN}; set HASSLE_UPDATE_SNAPSHOTS=1 to write it"
    assert actual == GOLDEN.read_text(encoding="utf-8")


def test_stub_golden_matches(snapshot: RegistrySnapshot) -> None:
    actual = generate_entities_stub(snapshot)
    _check_golden(actual)


def test_stub_contains_digit_leading_underscore_prefix(snapshot: RegistrySnapshot) -> None:
    stub = generate_entities_stub(snapshot)
    assert "_3d_printer" in stub
    # the real entity_id must be documented (docstring/comment) alongside it
    assert "sensor.3d_printer" in stub


def test_stub_contains_domain_classes_and_typed_attrs(snapshot: RegistrySnapshot) -> None:
    stub = generate_entities_stub(snapshot)
    assert "class _Light" in stub
    assert "hallway" in stub
    assert "class _BinarySensor" in stub
    assert "hall_motion" in stub


def test_stub_contains_typed_service_method(snapshot: RegistrySnapshot) -> None:
    stub = generate_entities_stub(snapshot)
    # LightEntity.turn_on(brightness_pct: int = ..., transition: float = ...)
    assert "def turn_on(" in stub
    assert "brightness_pct" in stub
    assert "transition" in stub


def test_stub_supports_indexing_form(snapshot: RegistrySnapshot) -> None:
    stub = generate_entities_stub(snapshot)
    assert "__getitem__" in stub
