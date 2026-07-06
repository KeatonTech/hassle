"""MILESTONES M10 test 5 (part 1/2) — bundle-declared template helpers count
as existing in validation (the ignore-glob half lives in
`packages/hassle-cli/tests/test_ignore_filtering_template_helpers.py`, next
to `hassle_cli.ignore_filter`, which this module doesn't depend on).

Mirrors `test_registry_validate.py::test_bundle_declared_helper_counts` (M3
milestone test 3) for `template_number`, proving `hassle.registry.validate`
needed zero changes: `_bundle_declared_keys` is `set(result.objects)`, which
already includes every prebuilt object regardless of kind.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hassle.compiler.bundle import compile_bundle
from hassle.registry.snapshot import RegistrySnapshot
from hassle.registry.validate import validate_bundle

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE = REPO_ROOT / "fixtures" / "registry" / "home.json"


@pytest.fixture(scope="module")
def snapshot() -> RegistrySnapshot:
    return RegistrySnapshot.load(FIXTURE)


def _write_bundle(tmp_path: Path, code: str) -> Path:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "helpers.py").write_text(code, encoding="utf-8")
    return bundle


def test_bundle_declared_template_helper_counts_as_existing(
    tmp_path: Path, snapshot: RegistrySnapshot
) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, service, state, template_number, when

MY_HELPER = template_number(
    name="Active Hvac Zones",
    state="{{ 1 }}",
    set_value={"action": "input_number.set_value", "data": {"value": "{{ value }}"}},
)

@automation(id="a", alias="A")
def a():
    when(state(MY_HELPER).to("3"))
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    assert not any(
        f.code == "unknown-entity" and "active_hvac_zones" in f.message for f in findings
    )


def test_undeclared_template_helper_reference_fails(
    tmp_path: Path, snapshot: RegistrySnapshot
) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, service, state, when

@automation(id="a", alias="A")
def a():
    when(state("template_number.totally_undeclared").to("3"))
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    assert any(
        f.code == "unknown-entity" and "template_number.totally_undeclared" in f.message
        for f in findings
    )
