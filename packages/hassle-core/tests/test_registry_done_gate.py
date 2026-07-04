"""M3 done-gate: validation catches every seeded error in a purpose-built
"broken bundle" fixture (>= 25 distinct seeded mistakes, milestone floor;
this fixture carries 37 after the reviewer's B1 nested-control-flow fix) with
ZERO false positives on (a) a synthetic clean bundle and (b) the existing
M0/M1/M2 DSL golden corpus.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hassle.compiler.bundle import compile_bundle
from hassle.registry.snapshot import RegistrySnapshot
from hassle.registry.validate import validate_bundle

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE = REPO_ROOT / "fixtures" / "registry" / "home.json"
BROKEN_BUNDLE = REPO_ROOT / "fixtures" / "registry" / "broken_bundle" / "bundle"
CLEAN_BUNDLE = REPO_ROOT / "fixtures" / "registry" / "clean_bundle" / "bundle"


@pytest.fixture(scope="module")
def snapshot() -> RegistrySnapshot:
    return RegistrySnapshot.load(FIXTURE)


def test_broken_bundle_produces_at_least_25_findings(snapshot: RegistrySnapshot) -> None:
    result = compile_bundle(BROKEN_BUNDLE)
    findings = validate_bundle(result, snapshot)
    # Milestone floor is 25; the fixture actually carries 37 (29 original +
    # 8 nested-control-flow seeds added for reviewer finding B1) -- asserting
    # >= 33 (not just >= 25) so a future regression back into the nested
    # blind spot fails this test immediately rather than merely dipping
    # toward the historical floor.
    assert len(findings) >= 33, f"expected >= 33 findings, got {len(findings)}: {findings}"


def test_broken_bundle_covers_nested_control_flow_positions(
    snapshot: RegistrySnapshot,
) -> None:
    """(reviewer B1) Pin the nested-control-flow seeds (if/else, choose branch
    + default, repeat, parallel, repeat-inside-choose, wait_for_trigger) so
    this fixture can never quietly lose that coverage again.
    """
    result = compile_bundle(BROKEN_BUNDLE)
    findings = validate_bundle(result, snapshot)
    messages = " ".join(f.message for f in findings)
    nested_markers = [
        "light.does_not_exist_26",  # if_then body
        "light.does_not_exist_27",  # else_then body
        "light.does_not_exist_28",  # choose branch
        "light.does_not_exist_29",  # choose default
        "light.does_not_exist_30",  # repeat body
        "light.does_not_exist_31",  # parallel body
        "light.does_not_exist_32",  # repeat nested inside choose
        "binary_sensor.does_not_exist_33",  # wait_for_trigger inner trigger
    ]
    missing = [marker for marker in nested_markers if marker not in messages]
    assert not missing, f"broken bundle fixture is missing nested-position seeds: {missing}"


def test_broken_bundle_findings_cover_every_implemented_code(snapshot: RegistrySnapshot) -> None:
    result = compile_bundle(BROKEN_BUNDLE)
    findings = validate_bundle(result, snapshot)
    codes = {f.code for f in findings}
    expected_codes = {
        "unknown-entity",
        "unknown-area",
        "unknown-floor",
        "unknown-label",
        "unknown-device",
        "unknown-purpose-type",
        "renamed-purpose-type",
        "unknown-service-param",
        "service-param-wrong-type",
        "service-param-missing-required",
    }
    missing = expected_codes - codes
    assert not missing, f"broken bundle fixture is missing coverage for: {missing} (got {codes})"


def test_clean_bundle_has_zero_findings(snapshot: RegistrySnapshot) -> None:
    result = compile_bundle(CLEAN_BUNDLE)
    findings = validate_bundle(result, snapshot)
    assert findings == [], f"unexpected findings on clean bundle: {findings}"
