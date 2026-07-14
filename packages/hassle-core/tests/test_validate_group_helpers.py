"""MILESTONES M21 test 5 -- bundle-declared group helpers count as existing
in validation, AND a group referencing a nonexistent member entity surfaces
the standard unknown-entity finding (file:line, fix) -- mirrors
`test_validate_template_helpers.py` (M10 test 5), plus the group-specific
"own entities= list is itself checked" half that has no template analogue
(a template helper's own body has no list-of-entity-ids field to check).
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


def test_bundle_declared_group_helper_counts_as_existing(
    tmp_path: Path, snapshot: RegistrySnapshot
) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, group_cover, service, state, when

MY_GROUP = group_cover(name="Downstairs Covers", entities=["cover.garage_door"])

@automation(id="a", alias="A")
def a():
    when(state(MY_GROUP).to("open"))
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    assert not any(
        f.code == "unknown-entity" and "downstairs_covers" in f.message for f in findings
    )


def test_undeclared_group_helper_reference_fails(
    tmp_path: Path, snapshot: RegistrySnapshot
) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, service, state, when

@automation(id="a", alias="A")
def a():
    when(state("group_cover.totally_undeclared").to("open"))
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    assert any(
        f.code == "unknown-entity" and "group_cover.totally_undeclared" in f.message
        for f in findings
    )


def test_group_referencing_nonexistent_member_entity_surfaces_unknown_entity(
    tmp_path: Path, snapshot: RegistrySnapshot
) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import group_cover

group_cover(name="Bad Group", entities=["cover.totally_made_up"])
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    matches = [
        f for f in findings if f.code == "unknown-entity" and "cover.totally_made_up" in f.message
    ]
    assert len(matches) == 1
    finding = matches[0]
    assert finding.file is not None and finding.file.endswith("helpers.py")
    assert finding.line is not None
    assert finding.fix is not None


def test_group_referencing_real_member_entity_does_not_flag(
    tmp_path: Path, snapshot: RegistrySnapshot
) -> None:
    bundle = _write_bundle(
        tmp_path,
        'from hassle import group_cover\n\n'
        'group_cover(name="Real Group", entities=["cover.garage_door"])\n',
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    assert not any(f.code == "unknown-entity" for f in findings)


def test_nested_group_referencing_bundle_declared_sibling_group_does_not_flag(
    tmp_path: Path, snapshot: RegistrySnapshot
) -> None:
    # A group whose member is ANOTHER bundle-declared group's own entity id
    # counts as existing, exactly like a template helper's declared entity
    # (`_bundle_declared_keys`'s `_GROUP_ENTITY_DOMAIN` widening).
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import group_cover

group_cover(name="Bay Window Top", entities=["cover.garage_door"])
group_cover(name="Entryway Top", entities=["cover.bay_window_top"])
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    assert not any(
        f.code == "unknown-entity" and "bay_window_top" in f.message for f in findings
    )
