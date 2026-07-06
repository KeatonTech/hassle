"""M9 error-message audit finding: `expr()`/`state(...).value`'s entity-ref
coercion previously raised a bare `TypeError` with no file:line (one variant
had a fix hint, the other didn't) -- reachable from ordinary bundle
authoring (`expr(state(["a", "b"]))` / `expr(123)`). Fixed by
`TemplateEntityRefError` (what/where/fix, snapshot-tested per R6).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from hassle import expr, state
from hassle.compiler.recording import recording
from hassle.compiler.templates import TemplateEntityRefError

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


def test_expr_on_list_valued_state_raises_with_location_and_fix() -> None:
    with recording(alias="x", id="x"), pytest.raises(TemplateEntityRefError) as excinfo:
        expr(state(["light.a", "light.b"]))
    msg = str(excinfo.value)
    assert "test_template_entity_ref_error.py" in msg  # where
    assert "Fix:" in msg
    _check_snapshot("template_entity_ref_list", _normalize(msg))


def test_expr_on_non_entity_value_raises_with_location_and_fix() -> None:
    with recording(alias="x", id="x"), pytest.raises(TemplateEntityRefError) as excinfo:
        expr(123)  # type: ignore[arg-type]
    msg = str(excinfo.value)
    assert "test_template_entity_ref_error.py" in msg
    assert "Fix:" in msg
    _check_snapshot("template_entity_ref_bad_type", _normalize(msg))
