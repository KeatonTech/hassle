"""`.pyi` stub generator (entities + typed service methods).

Golden-tests the generated stub content against `fixtures/registry/home.json`
byte-for-byte (a plain pytest-managed golden comparison, regenerated only via
`HASSLE_UPDATE_SNAPSHOTS=1`, mirroring the errors-snapshot pattern).

The per-entity friendly name is emitted as an attribute docstring -- a
string-literal statement immediately following the attribute declaration,
which pyright/Pylance surface on hover and in the completion documentation
pane -- rather than a trailing `#` comment (invisible to Pylance).
"""

from __future__ import annotations

import ast
import os
import subprocess
from pathlib import Path

import pytest

from hassle.registry.snapshot import AreaInfo, DeviceInfo, EntityInfo, RegistrySnapshot
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


def test_stub_entity_classes_inherit_str(snapshot: RegistrySnapshot) -> None:
    """Regression: every generated ``<Domain>Entity`` class must inherit
    ``str`` -- matching the REAL runtime type
    (``hassle.compiler.helpers.EntityRef(str)``). Before this,
    ``BinarySensorEntity``/``LightEntity``/etc. had no relationship to ``str``
    at all, so a decompiled bundle's ``state(e.binary_sensor.hall_motion)``
    was a pyright error (`reportArgumentType`) even though it is correct,
    runnable code.

    Every entity class also always carries the typed ``.state`` accessor
    property, so a domain with no services no longer collapses to the
    one-line ``class X(str): ...`` form -- ``BinarySensorEntity`` (a domain
    this fixture snapshot gives no services to) is exactly the case that
    used to collapse and now doesn't.
    """
    stub = generate_entities_stub(snapshot)
    assert "class LightEntity(str):" in stub
    assert "class BinarySensorEntity(str):" in stub
    assert "class BinarySensorEntity(str): ..." not in stub
    # No entity class may be left without the `str` base (would silently
    # regress this fix for one specific domain without failing the two
    # explicit checks above).
    import re

    class_lines = re.findall(r"^class \w+Entity[^:]*:", stub, flags=re.MULTILINE)
    assert class_lines, "expected at least one generated entity class"
    for line in class_lines:
        assert line.startswith(("class ", "class")) and "(str)" in line, (
            f"entity class not inheriting str: {line!r}"
        )


def test_stub_uses_attribute_docstrings_not_comments(snapshot: RegistrySnapshot) -> None:
    """The friendly name must be a docstring (a string-literal statement
    immediately following the attribute declaration), not a trailing `#`
    comment -- Pylance surfaces docstrings on hover/completion, never
    comments."""
    stub = generate_entities_stub(snapshot)
    lines = stub.splitlines()
    idx = next(i for i, line in enumerate(lines) if line.strip().startswith("hallway:"))
    assert lines[idx].rstrip().endswith("LightEntity")
    assert "#" not in lines[idx]
    doc_line = lines[idx + 1].strip()
    assert doc_line.startswith('"') or doc_line.startswith("'")
    assert "Hallway" in doc_line
    assert "light.hallway" in doc_line
    assert "area: Hallway" in doc_line


def test_stub_docstring_parses_as_module(snapshot: RegistrySnapshot) -> None:
    """The whole generated `.pyi` must remain valid Python (docstrings are
    real string-literal statements, not decoration)."""
    stub = generate_entities_stub(snapshot)
    ast.parse(stub)


def test_stub_docstring_immediately_follows_attribute(snapshot: RegistrySnapshot) -> None:
    """Pyright/Pylance only recognize a docstring when the string-literal
    statement is the *very next* statement after the attribute declaration
    (no blank line, no intervening statement) -- assert that shape for every
    entity attribute line in the generated `_EntitiesRegistry` domain classes."""
    stub = generate_entities_stub(snapshot)
    tree = ast.parse(stub)
    checked = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        body = node.body
        for i, stmt in enumerate(body):
            is_entity_attr = (
                isinstance(stmt, ast.AnnAssign)
                and isinstance(stmt.target, ast.Name)
                and isinstance(stmt.annotation, ast.Name)
                and stmt.annotation.id.endswith("Entity")
            )
            if not is_entity_attr:
                continue
            checked += 1
            assert i + 1 < len(body), f"attribute {ast.dump(stmt)} has no following docstring"
            next_stmt = body[i + 1]
            assert isinstance(next_stmt, ast.Expr) and isinstance(next_stmt.value, ast.Constant)
            assert isinstance(next_stmt.value.value, str)
    assert checked > 0


def test_stub_docstring_resolves_area_name(snapshot: RegistrySnapshot) -> None:
    stub = generate_entities_stub(snapshot)
    assert "area: Workshop" in stub  # sensor.3d_printer lives in the workshop area


def test_stub_docstring_handles_missing_area(snapshot: RegistrySnapshot) -> None:
    """`input_text.material_you_image_url_6814bc` has `area_id: null` in the
    fixture -- the docstring must omit the area clause entirely rather than
    emit `area: None`."""
    stub = generate_entities_stub(snapshot)
    lines = stub.splitlines()
    idx = next(
        i
        for i, line in enumerate(lines)
        if line.strip().startswith("material_you_image_url_6814bc:")
    )
    doc_line = lines[idx + 1]
    assert "area:" not in doc_line
    assert "None" not in doc_line


def _snapshot_with_entity(
    entity: EntityInfo,
    areas: list[AreaInfo] | None = None,
    devices: list[DeviceInfo] | None = None,
) -> RegistrySnapshot:
    return RegistrySnapshot(entities=[entity], areas=areas or [], devices=devices or [])


def test_stub_docstring_escapes_quotes_and_backslash() -> None:
    """Torture test: a display name containing both a
    double quote and a backslash must still produce a parseable, ruff-format-
    clean `.pyi`."""
    entity = EntityInfo(
        entity_id="sensor.torture",
        name='Weird "Name" With\\Backslash',
        area_id="a1",
    )
    snapshot = _snapshot_with_entity(entity, areas=[AreaInfo(area_id="a1", name="Area1")])
    stub = generate_entities_stub(snapshot)
    ast.parse(stub)  # must still parse
    # The name contains `"` but no `'`: ruff's quote preference (matched by
    # the generator) picks single quotes here, so the backslash is escaped
    # but the double quote is not.
    assert "'Weird \"Name\" With\\\\Backslash -- sensor.torture (area: Area1)'" in stub


def test_stub_docstring_escapes_both_quote_types() -> None:
    """A name containing both `"` and `'` forces double-quote-with-escape
    (matching ruff's fallback when neither quote is unescaped-safe)."""
    entity = EntityInfo(entity_id="sensor.both_quotes", name="""Has "double" and 'single'""")
    snapshot = _snapshot_with_entity(entity)
    stub = generate_entities_stub(snapshot)
    ast.parse(stub)
    assert '"Has \\"double\\" and \'single\'' in stub


def test_stub_docstring_falls_back_to_original_name() -> None:
    entity = EntityInfo(entity_id="sensor.fallback", name=None, original_name="Original Name")
    snapshot = _snapshot_with_entity(entity)
    stub = generate_entities_stub(snapshot)
    assert "Original Name" in stub


def test_stub_docstring_falls_back_to_entity_id_when_both_names_none() -> None:
    entity = EntityInfo(entity_id="sensor.no_name", name=None, original_name=None)
    snapshot = _snapshot_with_entity(entity)
    stub = generate_entities_stub(snapshot)
    lines = stub.splitlines()
    idx = next(i for i, line in enumerate(lines) if line.strip().startswith("no_name:"))
    doc_line = lines[idx + 1].strip()
    assert "sensor.no_name" in doc_line
    # No device resolves here -- entity_id must appear exactly ONCE in the
    # docstring, never the doubled "x -- x" wart.
    assert doc_line.count("sensor.no_name") == 1


def _line_after(stub: str, attr_prefix: str) -> str:
    lines = stub.splitlines()
    idx = next(i for i, line in enumerate(lines) if line.strip().startswith(attr_prefix))
    return lines[idx + 1].strip()


def test_stub_docstring_uses_device_name_when_entity_names_are_null() -> None:
    """`has_entity_name` integrations (Matter, etc.) leave BOTH `entity.name`
    and `entity.original_name` null -- the friendly name lives on the device
    instead (HA's own composition rule). Example:
    `cover.primary_bedroom_bedroom_privacy_curtain` with a device named
    "Primary Bedroom Privacy Curtain" via `name_by_user`."""
    device = DeviceInfo(
        device_id="dev1", name="Privacy Curtain", name_by_user="Primary Bedroom Privacy Curtain"
    )
    entity = EntityInfo(
        entity_id="cover.primary_bedroom_bedroom_privacy_curtain",
        name=None,
        original_name=None,
        device_id="dev1",
    )
    snapshot = _snapshot_with_entity(entity, devices=[device])
    stub = generate_entities_stub(snapshot)
    doc_line = _line_after(stub, "primary_bedroom_bedroom_privacy_curtain:")
    assert "Primary Bedroom Privacy Curtain" in doc_line
    # device.name_by_user (user override) wins over device.name.
    assert "-- Privacy Curtain" not in doc_line
    entity_id = "cover.primary_bedroom_bedroom_privacy_curtain"
    assert doc_line.count(entity_id) == 1


def test_stub_docstring_composes_device_name_with_original_name() -> None:
    """HA's `has_entity_name` friendly-name rule: when the entity has an
    `original_name` (a sub-entity label distinguishing it from siblings on
    the same device), the composed name is `device_name + " " +
    original_name` -- e.g. a device named "Kitchen Thermostat" with a
    sub-entity `original_name="Humidity"` reads as "Kitchen Thermostat
    Humidity"."""
    device = DeviceInfo(device_id="dev2", name="Kitchen Thermostat")
    entity = EntityInfo(
        entity_id="sensor.kitchen_thermostat_humidity",
        name=None,
        original_name="Humidity",
        device_id="dev2",
    )
    snapshot = _snapshot_with_entity(entity, devices=[device])
    stub = generate_entities_stub(snapshot)
    doc_line = _line_after(stub, "kitchen_thermostat_humidity:")
    assert "Kitchen Thermostat Humidity" in doc_line


def test_stub_docstring_device_resolution_prefers_name_by_user_with_original_name() -> None:
    """`name_by_user` still wins over `name` even when composing with
    `original_name`."""
    device = DeviceInfo(device_id="dev3", name="Integration Name", name_by_user="My Thermostat")
    entity = EntityInfo(
        entity_id="sensor.my_thermostat_humidity",
        name=None,
        original_name="Humidity",
        device_id="dev3",
    )
    snapshot = _snapshot_with_entity(entity, devices=[device])
    stub = generate_entities_stub(snapshot)
    doc_line = _line_after(stub, "my_thermostat_humidity:")
    assert "My Thermostat Humidity" in doc_line
    assert "Integration Name" not in doc_line


def test_stub_docstring_no_device_resolution_falls_back_to_entity_id_once() -> None:
    """`device_id` set but unresolvable (not in `snapshot.devices`) must still
    land on the entity_id fallback -- the entity_id must appear exactly once
    in the docstring, never the doubled "entity_id -- entity_id" form."""
    entity = EntityInfo(
        entity_id="sensor.orphaned_device_ref",
        name=None,
        original_name=None,
        device_id="does_not_exist",
    )
    snapshot = _snapshot_with_entity(entity, devices=[])
    stub = generate_entities_stub(snapshot)
    doc_line = _line_after(stub, "orphaned_device_ref:")
    entity_id = "sensor.orphaned_device_ref"
    assert entity_id in doc_line
    assert doc_line.count(entity_id) == 1
    assert " -- " not in doc_line or doc_line.count(entity_id) == 1


def test_stub_docstring_device_with_no_name_at_all_falls_back_to_entity_id_once() -> None:
    """A device resolves but has neither `name_by_user` nor `name` -- falls
    through to `original_name`, then entity_id, still without doubling."""
    device = DeviceInfo(device_id="dev4", name=None, name_by_user=None)
    entity = EntityInfo(
        entity_id="sensor.nameless_device_entity",
        name=None,
        original_name=None,
        device_id="dev4",
    )
    snapshot = _snapshot_with_entity(entity, devices=[device])
    stub = generate_entities_stub(snapshot)
    doc_line = _line_after(stub, "nameless_device_entity:")
    entity_id = "sensor.nameless_device_entity"
    assert doc_line.count(entity_id) == 1


def test_stub_docstring_long_line_truncates_area_first() -> None:
    """The >100-char fallback rule: truncate/drop the area clause first,
    keeping the display name + entity_id (the load-bearing part for the
    digit-leading rule) intact."""
    long_area_name = "A" * 90
    entity = EntityInfo(entity_id="sensor.long_case", name="A Name", area_id="a1")
    snapshot = _snapshot_with_entity(entity, areas=[AreaInfo(area_id="a1", name=long_area_name)])
    stub = generate_entities_stub(snapshot)
    lines = stub.splitlines()
    idx = next(i for i, line in enumerate(lines) if line.strip().startswith("long_case:"))
    doc_line = lines[idx + 1]
    assert len(doc_line) <= 100
    assert "A Name" in doc_line
    assert "sensor.long_case" in doc_line
    assert long_area_name not in doc_line


def test_stub_is_ruff_format_clean(snapshot: RegistrySnapshot, tmp_path: Path) -> None:
    """The generator must emit already-format-clean output (module docstring,
    stubs.py:100-104's no-shell-out constraint) -- verified here by actually
    running `ruff format --diff` over a generated stub."""
    stub = generate_entities_stub(snapshot)
    pyi_path = tmp_path / "entities.pyi"
    pyi_path.write_text(stub, encoding="utf-8")
    result = subprocess.run(
        ["ruff", "format", "--diff", str(pyi_path)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"generated stub is not ruff-format-clean:\n{result.stdout}\n{result.stderr}"
    )


def test_stub_no_longer_uses_trailing_comment_form(snapshot: RegistrySnapshot) -> None:
    """Regression guard: the old `# entity_id - "name"` trailing-comment form
    is fully superseded by the docstring; no domain-class attribute line may
    carry a `#` comment."""
    stub = generate_entities_stub(snapshot)
    for line in stub.splitlines():
        stripped = line.strip()
        is_attr_line = (
            ":" in stripped
            and stripped.endswith("Entity")
            and not stripped.startswith(("class", "def"))
        )
        if is_attr_line:
            assert "#" not in line, f"attribute line still uses comment form: {line!r}"
