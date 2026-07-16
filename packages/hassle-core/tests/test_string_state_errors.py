"""Error surface for the string-state vocabulary (what/where/fix,
snapshot-tested).

`.eq()`/`.ne()` against something that isn't a `TemplateExpr` or a bare
Python literal (`int`/`float`/`str`/`bool`) -- e.g. a list/dict -- would
otherwise silently `repr()` into nonsense Jinja; `state_of()` on a
non-entity arg reuses the existing `TemplateEntityRefError` (same class
`expr()` already raises for this, mirroring expr()'s argument handling
exactly).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hassle.compiler.builders import state
from hassle.compiler.recording import recording
from hassle.compiler.templates import (
    TemplateComparisonOperandError,
    TemplateEntityRefError,
    expr,
    state_of,
)
from hassle_dev.snapshots import check_snapshot, normalize_error

SNAP_DIR = Path(__file__).resolve().parent / "snapshots" / "errors"


def _check_snapshot(name: str, actual: str) -> None:
    check_snapshot(SNAP_DIR, name, actual)


def _normalize(msg: str) -> str:
    return normalize_error(msg, mask_lines_for=Path(__file__).name)


def test_state_of_on_non_entity_arg_raises_with_location_and_fix() -> None:
    with recording(alias="x", id="x"), pytest.raises(TemplateEntityRefError) as excinfo:
        state_of(123)  # type: ignore[arg-type]
    msg = str(excinfo.value)
    assert "test_string_state_errors.py" in msg  # where
    assert "Fix:" in msg
    _check_snapshot("state_of_non_entity_arg", _normalize(msg))


def test_state_of_on_list_valued_state_raises_with_location_and_fix() -> None:
    with recording(alias="x", id="x"), pytest.raises(TemplateEntityRefError) as excinfo:
        state_of(state(["light.a", "light.b"]))
    msg = str(excinfo.value)
    assert "test_string_state_errors.py" in msg
    assert "Fix:" in msg
    _check_snapshot("state_of_list_valued_state", _normalize(msg))


def test_eq_against_non_literal_non_expr_raises_with_location_and_fix() -> None:
    with recording(alias="x", id="x"), pytest.raises(TemplateComparisonOperandError) as excinfo:
        state_of("sensor.x").eq(["a", "b"])  # type: ignore[arg-type]
    msg = str(excinfo.value)
    assert "test_string_state_errors.py" in msg
    assert "Fix:" in msg
    _check_snapshot("template_comparison_operand_list", _normalize(msg))


def test_ne_against_non_literal_non_expr_raises_with_location_and_fix() -> None:
    with recording(alias="x", id="x"), pytest.raises(TemplateComparisonOperandError) as excinfo:
        expr("sensor.x").ne({"a": 1})  # type: ignore[arg-type]
    msg = str(excinfo.value)
    assert "test_string_state_errors.py" in msg
    assert "Fix:" in msg
    _check_snapshot("template_comparison_operand_dict", _normalize(msg))


def test_in_applies_the_same_operand_check_per_element() -> None:
    """Polish-batch item 5: `.in_([...])` must validate EACH element with the
    same `_check_comparison_operand` `.eq()`/`.ne()` use -- otherwise a bad
    element (e.g. a dict) would silently `repr()` into nonsense Jinja inside
    the `in [...]` list, exactly the failure mode `.eq()`/`.ne()` were
    already protected against."""
    with recording(alias="x", id="x"), pytest.raises(TemplateComparisonOperandError) as excinfo:
        state_of("sensor.x").in_(["a", {"b": 1}])  # type: ignore[list-item]
    msg = str(excinfo.value)
    assert "test_string_state_errors.py" in msg
    assert "Fix:" in msg
    _check_snapshot("template_comparison_operand_in_element", _normalize(msg))


def test_in_with_all_valid_elements_still_compiles_fine() -> None:
    # Regression guard: the new per-element check must not reject the
    # ordinary, already-golden-tested case.
    result = state_of("sensor.x").in_(["a", "b", 3, True])
    assert result.to_template() == "{{ states('sensor.x') in ['a', 'b', 3, True] }}"
