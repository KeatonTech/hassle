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

**Scoped to NEW declarations only** (smoke #7 field evidence; §17.5 amended
2026-07-05): the slug-derivation rule only holds for the WS-API creation path
that Hassle's own push uses. A live registry's ``.storage`` can legitimately
hold helpers created some other way (e.g. an external integration writing
``.storage`` directly) whose id does NOT equal ``slugify(name)`` -- those are
adopted, already-live truth, and "fixing" them by changing the id would break
the bundle's mapping to a real, pre-existing entity (I2). So the Finding fires
only when the declared ``<domain>.<id>`` entity is NOT already present in the
registry snapshot -- i.e. a genuinely new helper Hassle would create via the
WS path, where the slug rule actually bites. An adopted helper whose id is
already in the snapshot produces zero findings, regardless of name mismatch.
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
    (bundle / "automation.py").write_text(code, encoding="utf-8")
    return bundle


def _normalize(msg: str) -> str:
    return normalize_error(msg, mask_lines_for=Path(__file__).name)


def _check_snapshot(name: str, actual: str) -> None:
    check_snapshot(SNAP_DIR, name, actual)


def test_helper_id_mismatched_with_name_slug_flagged(
    tmp_path: Path, snapshot: RegistrySnapshot
) -> None:
    # `guest_room_mode` is NOT in the fixture registry snapshot -- this is a
    # genuinely new declaration Hassle would create via the WS path, where
    # the slug rule bites (see the scoping tests further below for the
    # adopted/present-in-snapshot counterpart).
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, input_boolean, service

guest_flag = input_boolean(id="guest_room_mode", name="Guest Room Flag")

@automation(id="a", alias="A")
def a():
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    matches = [f for f in findings if f.code == "helper-id-name-mismatch"]
    assert matches, f"expected a helper-id-name-mismatch finding, got: {findings}"
    assert "guest_room_mode" in matches[0].message
    assert "guest_room_flag" in matches[0].fix or "guest_room_flag" in matches[0].message
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


# Field evidence (owner's live registry): fixtures/registry/home.json seeds
# `input_text.material_you_image_url_6814bc`, named "Material You Base Color
# Source Image Path/URL Kai" -- an id that does NOT equal slugify(name),
# adopted from an external integration that wrote `.storage` directly (not
# via the WS-API create path Hassle's push uses).


def test_adopted_helper_with_mismatched_id_present_in_snapshot_is_not_flagged(
    tmp_path: Path, snapshot: RegistrySnapshot
) -> None:
    """A declared helper whose id+domain already exists in the registry
    snapshot is an *adopted* helper, not a new WS-API creation -- the slug
    rule never bites it (nothing will be freshly `create`d), so it is exempt
    from this Finding regardless of the name/id mismatch.
    """
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, input_text, service

img = input_text(
    id="material_you_image_url_6814bc",
    name="Material You Base Color Source Image Path/URL Kai",
)

@automation(id="a", alias="A")
def a():
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    assert not [f for f in findings if f.code == "helper-id-name-mismatch"]


def test_same_mismatched_helper_absent_from_snapshot_is_flagged(tmp_path: Path) -> None:
    """The exact same declaration as the "present in snapshot" test above
    (same id, same name, same mismatch) -- but validated against a snapshot
    that does NOT contain `input_text.material_you_image_url_6814bc`. Absent
    from the snapshot means Hassle would `create` it fresh via the WS path,
    where the slug rule bites -- so, unlike the adopted case, this must fire,
    with fix text explaining the new-vs-adopted scoping.
    """
    empty_snapshot = RegistrySnapshot()
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, input_text, service

img = input_text(
    id="material_you_image_url_6814bc",
    name="Material You Base Color Source Image Path/URL Kai",
)

@automation(id="a", alias="A")
def a():
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, empty_snapshot)
    matches = [f for f in findings if f.code == "helper-id-name-mismatch"]
    assert matches, f"expected a helper-id-name-mismatch finding, got: {findings}"
    # An empty snapshot ("no snapshot available") can't distinguish new from
    # adopted, so this is the softened "note" path, not "error".
    assert matches[0].severity == "note"
    _check_snapshot("helper_id_name_mismatch_no_snapshot", _normalize(str(matches[0])))


def test_new_helper_with_mismatched_id_absent_from_real_snapshot_is_flagged(
    tmp_path: Path, snapshot: RegistrySnapshot
) -> None:
    """A mismatch on an id/domain that is absent from a *real* (non-empty)
    registry snapshot -- a genuinely new declaration Hassle would create via
    the WS path, where the slug rule bites -- must fire at full "error"
    severity, with fix text explaining the new-vs-adopted scoping.
    """
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, input_boolean, service

guest_flag = input_boolean(id="guest_room_mode", name="Guest Room Flag")

@automation(id="a", alias="A")
def a():
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    matches = [f for f in findings if f.code == "helper-id-name-mismatch"]
    assert matches, f"expected a helper-id-name-mismatch finding, got: {findings}"
    assert matches[0].severity == "error"


def test_adopted_helper_exempt_via_manifest_keys_even_when_entity_renamed(tmp_path) -> None:
    # Field evidence (owner bundle): a helper's storage id can have NO matching
    # entity in the registry (the entity was renamed -- "front_bedroom_occupied"
    # became "Office Occupied" with a renamed entity_id). Entity-id inference
    # cannot identify such adopted helpers; manifest membership can: if the key
    # was pulled, it is live truth.
    from hassle.registry.snapshot import RegistrySnapshot
    from hassle.registry.validate import validate_bundle

    bundle = _write_bundle(
        tmp_path,
        "from hassle import input_boolean\n"
        "front_bedroom_occupied = input_boolean(\n"
        '    id="front_bedroom_occupied", name="Office Occupied"\n'
        ")\n",
    )
    result = compile_bundle(bundle)
    snapshot = RegistrySnapshot.model_validate(
        {"entities": [{"entity_id": "light.something_else", "name": "x"}]}
    )
    # Without the adopted set: fires (absent from snapshot, snapshot non-empty).
    assert any(f.code == "helper-id-name-mismatch" for f in validate_bundle(result, snapshot))
    # With the manifest-derived adopted set: exempt.
    findings = validate_bundle(
        result, snapshot, adopted_helper_keys=frozenset({"input_boolean:front_bedroom_occupied"})
    )
    assert not [f for f in findings if f.code == "helper-id-name-mismatch"], findings
