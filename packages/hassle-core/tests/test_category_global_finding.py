"""M12 test 2 -- a `CATEGORY` module global that does not slugify to its
file's stem produces a validation Finding (what/where/fix, snapshot-tested).

`slugify(CATEGORY)` MUST equal the file stem (MILESTONES M12's binding
semantics block) -- mismatch is a distinct, additive Finding type
(`category-slug-mismatch`), never a hard compile error (the object itself
must still validate/apply fine; MILESTONES M11 test-3-style isolation, this
milestone's test 2).
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


def _check_snapshot(name: str, actual: str) -> None:
    path = SNAP_DIR / f"{name}.txt"
    if os.environ.get("HASSLE_UPDATE_SNAPSHOTS"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual + "\n", encoding="utf-8")
    assert path.is_file(), f"missing snapshot {path}; set HASSLE_UPDATE_SNAPSHOTS=1 to write it"
    assert actual == path.read_text(encoding="utf-8").rstrip("\n")


def _normalize(msg: str) -> str:
    return re.sub(r"(/[^\s:]+/)([^/\s:]+\.py)", r"\2", msg)


def _write_bundle(tmp_path: Path, filename: str, code: str) -> Path:
    bundle = tmp_path / "bundle"
    bundle.mkdir(exist_ok=True)
    (bundle / "automations").mkdir(exist_ok=True)
    (bundle / "automations" / filename).write_text(code, encoding="utf-8")
    return bundle


def test_category_mismatched_with_file_stem_is_flagged(
    tmp_path: Path, snapshot: RegistrySnapshot
) -> None:
    bundle = _write_bundle(
        tmp_path,
        "automatic_hvac.py",
        '''
from hassle import automation, service, state, when

CATEGORY = "Totally Different Name"


@automation(id="auto_hvac_1", alias="Keep temp steady")
def auto_hvac_1():
    when(state("binary_sensor.hall_motion").to("on"))
    service("climate.turn_on", target={"entity_id": "climate.living_room"})
''',
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    matches = [f for f in findings if f.code == "category-slug-mismatch"]
    assert matches, f"expected a category-slug-mismatch finding, got: {findings}"
    assert "automatic_hvac" in matches[0].message
    assert "Totally Different Name" in matches[0].message
    _check_snapshot("category_slug_mismatch", _normalize(str(matches[0])))


def test_category_matching_file_stem_is_clean(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    bundle = _write_bundle(
        tmp_path,
        "automatic_hvac.py",
        '''
from hassle import automation, service, state, when

CATEGORY = "Automatic HVAC"


@automation(id="auto_hvac_1", alias="Keep temp steady")
def auto_hvac_1():
    when(state("binary_sensor.hall_motion").to("on"))
    service("climate.turn_on", target={"entity_id": "climate.living_room"})
''',
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    assert not [f for f in findings if f.code == "category-slug-mismatch"]


def test_mismatch_does_not_block_other_object_validation(
    tmp_path: Path, snapshot: RegistrySnapshot
) -> None:
    """M11 test-3-style isolation: a CATEGORY mismatch is its own Finding but
    never prevents the object itself from validating (no other findings for
    the well-formed automation body)."""
    bundle = _write_bundle(
        tmp_path,
        "automatic_hvac.py",
        '''
from hassle import automation, service, state, when

CATEGORY = "Nonsense"


@automation(id="auto_hvac_1", alias="Keep temp steady")
def auto_hvac_1():
    when(state("binary_sensor.hall_motion").to("on"))
    service("climate.turn_on", target={"entity_id": "climate.living_room"})
''',
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    assert [f.code for f in findings] == ["category-slug-mismatch"]
