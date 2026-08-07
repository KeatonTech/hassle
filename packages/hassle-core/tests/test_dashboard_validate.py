"""`validate_bundle` over dashboard card trees (docs/internals/dashboards-design.md
§8's tier-2 row): the same did-you-mean `unknown-entity`/`unknown-area`
Finding shape automations get, driven by `hassle.registry.dashboard_extract`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hassle.compiler.bundle import compile_bundle
from hassle.registry.snapshot import RegistrySnapshot
from hassle.registry.validate import validate_bundle
from hassle_dev.snapshots import check_snapshot, normalize_error

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE = REPO_ROOT / "fixtures" / "registry" / "home.json"
SNAP_DIR = Path(__file__).resolve().parent / "snapshots" / "findings"


@pytest.fixture(scope="module")
def snapshot() -> RegistrySnapshot:
    return RegistrySnapshot.load(FIXTURE)


def _write_bundle(tmp_path: Path, code: str) -> Path:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "dash.py").write_text(code, encoding="utf-8")
    return bundle


def _normalize(msg: str) -> str:
    return normalize_error(msg, mask_lines_for=Path(__file__).name)


def test_unknown_entity_on_a_card_is_flagged(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import dashboard, section, view
from hassle import cards as c

@dashboard(url_path="a-b")
def d():
    with view(title="V"), section():
        c.tile("light.hallwya")
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    bad = [f for f in findings if f.code == "unknown-entity"]
    assert bad, findings
    assert any("light.hallwya" in f.message for f in bad)
    assert any("light.hallway" in f.fix for f in bad)
    assert bad[0].file is not None and bad[0].line is not None


def test_unknown_entity_on_a_card_snapshot(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import dashboard, section, view
from hassle import cards as c

@dashboard(url_path="a-b")
def d():
    with view(title="V"), section():
        c.tile("light.hallwya")
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    bad = next(f for f in findings if f.code == "unknown-entity")
    check_snapshot(SNAP_DIR, "dashboard_unknown_entity_card", _normalize(str(bad)))


def test_known_entity_on_a_card_is_clean(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import dashboard, section, view
from hassle import cards as c

@dashboard(url_path="a-b")
def d():
    with view(title="V"), section():
        c.tile("light.hallway")
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    assert not any(f.code == "unknown-entity" for f in findings)


def test_unknown_area_on_the_area_card_is_flagged(
    tmp_path: Path, snapshot: RegistrySnapshot
) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import dashboard, section, view
from hassle import cards as c

@dashboard(url_path="a-b")
def d():
    with view(title="V"), section():
        c.area("living_rooom")
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    bad = [f for f in findings if f.code == "unknown-area"]
    assert bad, findings
    assert any("living_rooom" in f.message for f in bad)
    assert any("living_room" in f.fix for f in bad)


def test_known_area_on_the_area_card_is_clean(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import dashboard, section, view
from hassle import cards as c

@dashboard(url_path="a-b")
def d():
    with view(title="V"), section():
        c.area("living_room")
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    assert not any(f.code == "unknown-area" for f in findings)


def test_bundle_declared_helper_referenced_by_a_card_does_not_false_positive(
    tmp_path: Path, snapshot: RegistrySnapshot
) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import dashboard, input_boolean, section, view
from hassle import cards as c

guest_flag = input_boolean(id="brand_new_flag", name="Brand New Flag")

@dashboard(url_path="a-b")
def d():
    with view(title="V"), section():
        c.tile(guest_flag)
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    assert not any(f.code == "unknown-entity" for f in findings)


def test_unknown_entity_inside_a_visibility_condition_is_flagged(
    tmp_path: Path, snapshot: RegistrySnapshot
) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import dashboard, section, view
from hassle import cards as c
from hassle.cards import cond

@dashboard(url_path="a-b")
def d():
    with view(title="V"), section():
        c.tile("light.hallway", visibility=[cond.state("input_boolean.does_not_exist", "on")])
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    bad = [f for f in findings if f.code == "unknown-entity"]
    assert any("input_boolean.does_not_exist" in f.message for f in bad)
