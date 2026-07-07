"""M16 test 5 -- error surface for the string-state vocabulary (R6: what/where
/fix, snapshot-tested).

`.eq()`/`.ne()` against something that isn't a `TemplateExpr` or a bare
Python literal (`int`/`float`/`str`/`bool`) -- e.g. a list/dict -- would
otherwise silently `repr()` into nonsense Jinja; `state_of()` on a
non-entity arg reuses the existing `TemplateEntityRefError` (same class
`expr()` already raises for this, MILESTONES M16 design note: "mirroring
expr()'s argument handling exactly").
"""

from __future__ import annotations

import re
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

SNAP_DIR = Path(__file__).resolve().parent / "snapshots" / "errors"


def _check_snapshot(name: str, actual: str) -> None:
    import os

    path = SNAP_DIR / f"{name}.txt"
    if os.environ.get("HASSLE_UPDATE_SNAPSHOTS"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual + "\n", encoding="utf-8")
    assert path.is_file(), f"missing snapshot {path}; set HASSLE_UPDATE_SNAPSHOTS=1 to write it"
    assert actual == path.read_text(encoding="utf-8").rstrip("\n")


def _normalize(msg: str) -> str:
    return re.sub(r"(/[^\s:]+/)([^/\s:]+\.py)", r"\2", msg)


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
