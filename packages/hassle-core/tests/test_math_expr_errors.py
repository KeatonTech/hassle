"""R6 error snapshot for the M1.1 math-expression workstream's one new error
class, PythonMathMisuseError: Python's stdlib `math.*`/`float()`/`int()`/
`round()`/`math.trunc()` applied to a runtime TemplateExpr (the `__float__`/
`__int__`/`__round__`/`__trunc__` traps). Same pattern as
test_compile_errors.py / test_templates_macros_errors.py. One snapshot covers
the message shape (shared by every trigger of this error class); the other
trigger sites (round()/math.trunc()) are asserted against the same class and
mention the right function name, without duplicating the snapshot file.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from hassle.compiler.errors import CompileError
from hassle.compiler.templates import var
from hassle_dev.snapshots import check_snapshot, normalize_error

SNAP_DIR = Path(__file__).resolve().parent / "snapshots" / "errors"


def _check_snapshot(name: str, actual: str) -> None:
    check_snapshot(SNAP_DIR, name, actual)


def _normalize(msg: str) -> str:
    return normalize_error(msg, mask_lines_for=Path(__file__).name)


def test_stdlib_math_misuse_error_message() -> None:
    with pytest.raises(CompileError) as excinfo:
        math.cos(var("x"))
    _check_snapshot("python_math_misuse", _normalize(str(excinfo.value)))


def test_builtin_round_misuse_same_error_class_and_mentions_round() -> None:
    with pytest.raises(CompileError) as excinfo:
        round(var("x"))
    assert "round(" in str(excinfo.value)


def test_stdlib_math_trunc_misuse_same_error_class_and_mentions_trunc() -> None:
    with pytest.raises(CompileError) as excinfo:
        math.trunc(var("x"))
    assert "trunc(" in str(excinfo.value)
