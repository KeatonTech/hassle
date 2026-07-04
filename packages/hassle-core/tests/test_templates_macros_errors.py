"""R6 error snapshots for the templates/macros/scripts workstream.

Same pattern as test_compile_errors.py: each user-facing error states *what*,
*where* (file:line), and *the fix*, in one paragraph, snapshot-tested under
tests/snapshots/errors/.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from hassle.compiler import NoRecordingContextError, UnknownParamError, compile_bundle

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "dsl"
SNAP_DIR = Path(__file__).resolve().parent / "snapshots" / "errors"


def _check_snapshot(name: str, actual: str) -> None:
    path = SNAP_DIR / f"{name}.txt"
    if os.environ.get("HASSLE_UPDATE_SNAPSHOTS"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual + "\n", encoding="utf-8")
    assert path.is_file(), f"missing snapshot {path}; set HASSLE_UPDATE_SNAPSHOTS=1 to write it"
    assert actual == path.read_text(encoding="utf-8").rstrip("\n")


def _normalize(msg: str) -> str:
    """Replace absolute paths with a stable basename so snapshots are portable."""
    return re.sub(r"(/[^\s:]+/)([^/\s:]+\.py)", r"\2", msg)


def test_macro_outside_context_error_message() -> None:
    with pytest.raises(NoRecordingContextError) as excinfo:
        compile_bundle(FIXTURES / "macro_outside_context" / "bundle")
    _check_snapshot("macro_outside_context", _normalize(str(excinfo.value)))


def test_param_unknown_name_error_message() -> None:
    with pytest.raises(UnknownParamError) as excinfo:
        compile_bundle(FIXTURES / "shared_script_param_unknown" / "bundle")
    _check_snapshot("param_unknown_name", _normalize(str(excinfo.value)))


def test_param_outside_context_error_message() -> None:
    from hassle.compiler import NoParamContextError
    from hassle.compiler.recording import recording
    from hassle.compiler.scripts import param

    with recording(alias="x", id="x"), pytest.raises(NoParamContextError) as excinfo:
        param("times")
    _check_snapshot("param_outside_context", _normalize(str(excinfo.value)))


def test_raw_automation_non_json_serializable_error_message() -> None:
    from hassle.compiler.raw_automation import (
        RawAutomationNotJSONSerializableError,
        build_raw_automation,
    )

    class Weird:
        pass

    with pytest.raises(RawAutomationNotJSONSerializableError) as excinfo:
        build_raw_automation(id="weird_raw", alias="x", data=Weird())
    _check_snapshot("raw_automation_not_json", _normalize(str(excinfo.value)))
