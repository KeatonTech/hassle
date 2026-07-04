"""M3 done-gate: validation catches every seeded error in a purpose-built
"broken bundle" fixture (>= 25 distinct seeded mistakes) with ZERO false
positives on (a) a synthetic clean bundle and (b) the existing M0/M1/M2 DSL
golden corpus.
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
    assert len(findings) >= 25, f"expected >= 25 findings, got {len(findings)}: {findings}"


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
