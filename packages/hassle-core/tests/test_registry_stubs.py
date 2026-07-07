"""M3 milestone test 5: `.pyi` stub generator (entities + typed service methods).

Golden-tests the generated stub content against `fixtures/registry/home.json`
byte-for-byte (a plain pytest-managed golden comparison, regenerated only via
`HASSLE_UPDATE_SNAPSHOTS=1`, mirroring the errors-snapshot pattern).

ux/stub-docstrings: the per-entity friendly name moved from a trailing `#`
comment (invisible to Pylance) to an attribute docstring -- a string-literal
statement immediately following the attribute declaration, which pyright/
Pylance surface on hover and in the completion documentation pane.
"""

from __future__ import annotations

import ast
import os
import subprocess
from pathlib import Path

import pytest

from hassle.registry.snapshot import AreaInfo, EntityInfo, RegistrySnapshot
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
    entity: EntityInfo, areas: list[AreaInfo] | None = None
) -> RegistrySnapshot:
    return RegistrySnapshot(entities=[entity], areas=areas or [])


def test_stub_docstring_escapes_quotes_and_backslash() -> None:
    """Torture test (ux/stub-docstrings): a display name containing both a
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


def test_stub_docstring_long_line_truncates_area_first() -> None:
    """The >100-char fallback rule (R7): truncate/drop the area clause first,
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
