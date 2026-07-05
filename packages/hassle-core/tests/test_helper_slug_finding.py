"""M7 (owner UX, docs/ha-api-notes.md §17.5 finding): a helper declaration whose
``id=`` does not match ``slugify(name)`` gets a validation Finding.

Real HA storage-collection ``create`` derives the item's identity by
slugifying ``name`` and **ignores any caller-supplied id** (§17.5). So if a
bundle declares ``input_boolean(id="guest_mode", name="Guest Flag", ...)``,
HA will actually assign the identity ``guest_flag`` -- silently breaking the
id<->entity mapping the bundle (and the sync engine's object keys) assume.
This is a distinct, additive Finding type (`helper-id-name-mismatch`),
surfaced by `hassle validate` (M7), snapshot-tested per R6/the milestone's
Finding rubric (what/where/fix).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from hassle.compiler.bundle import compile_bundle
from hassle.registry.snapshot import RegistrySnapshot
from hassle.registry.validate import validate_bundle

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE = REPO_ROOT / "fixtures" / "registry" / "home.json"
SNAP_DIR = Path(__file__).resolve().parent / "snapshots" / "findings"


@pytest.fixture(scope="module")
def snapshot() -> RegistrySnapshot:
    return RegistrySnapshot.load(FIXTURE)


def _write_bundle(tmp_path: Path, code: str) -> Path:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "automation.py").write_text(code, encoding="utf-8")
    return bundle


def _normalize(msg: str) -> str:
    return re.sub(r"(/[^\s:]+/)([^/\s:]+\.py)", r"\2", msg)


def _check_snapshot(name: str, actual: str) -> None:
    path = SNAP_DIR / f"{name}.txt"
    if os.environ.get("HASSLE_UPDATE_SNAPSHOTS"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual + "\n", encoding="utf-8")
    assert path.is_file(), f"missing snapshot {path}; set HASSLE_UPDATE_SNAPSHOTS=1 to write it"
    assert actual == path.read_text(encoding="utf-8").rstrip("\n")


def test_helper_id_mismatched_with_name_slug_flagged(
    tmp_path: Path, snapshot: RegistrySnapshot
) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, input_boolean, service

guest_flag = input_boolean(id="guest_mode", name="Guest Flag")

@automation(id="a", alias="A")
def a():
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    matches = [f for f in findings if f.code == "helper-id-name-mismatch"]
    assert matches, f"expected a helper-id-name-mismatch finding, got: {findings}"
    assert "guest_mode" in matches[0].message
    assert "guest_flag" in matches[0].fix or "guest_flag" in matches[0].message
    _check_snapshot("helper_id_name_mismatch", _normalize(str(matches[0])))


def test_helper_id_matching_name_slug_is_clean(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, input_boolean, service

guest_flag = input_boolean(id="guest_flag", name="Guest Flag")

@automation(id="a", alias="A")
def a():
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    assert not [f for f in findings if f.code == "helper-id-name-mismatch"]


def test_helper_with_no_name_is_not_flagged(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    # A helper with no `name=` has nothing to slugify against; HA would derive
    # from the domain default in that case (id-authoring elsewhere is the
    # user's own business) -- this check only fires when `name` is present.
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, input_boolean, service

guest_flag = input_boolean(id="guest_mode")

@automation(id="a", alias="A")
def a():
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    assert not [f for f in findings if f.code == "helper-id-name-mismatch"]
