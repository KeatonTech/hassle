"""R6 error snapshots for the templates/macros/scripts workstream.

Same pattern as test_compile_errors.py: each user-facing error states *what*,
*where* (file:line), and *the fix*, in one paragraph, snapshot-tested under
tests/snapshots/errors/.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hassle.compiler import (
    NoRecordingContextError,
    UnknownFieldError,
    UnknownParamError,
    compile_bundle,
)
from hassle_dev.snapshots import check_snapshot, normalize_error

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "dsl"

SNAP_DIR = Path(__file__).resolve().parent / "snapshots" / "errors"


def _check_snapshot(name: str, actual: str) -> None:
    check_snapshot(SNAP_DIR, name, actual)


def _normalize(msg: str) -> str:
    return normalize_error(msg, mask_lines_for=Path(__file__).name)


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


def test_unknown_field_call_kwarg_error_message() -> None:
    with pytest.raises(UnknownFieldError) as excinfo:
        compile_bundle(FIXTURES / "shared_script_rich_fields_unknown_call_kwarg" / "bundle")
    _check_snapshot("unknown_field_call_kwarg", _normalize(str(excinfo.value)))


def test_shared_script_param_range_misuse_error_message() -> None:
    from hassle.compiler import SharedScriptParamMisuseError

    with pytest.raises(SharedScriptParamMisuseError) as excinfo:
        compile_bundle(FIXTURES / "shared_script_param_range_misuse" / "bundle")
    _check_snapshot("shared_script_param_range_misuse", _normalize(str(excinfo.value)))


def test_shared_script_param_if_misuse_error_message() -> None:
    from hassle.compiler import SharedScriptParamMisuseError

    with pytest.raises(SharedScriptParamMisuseError) as excinfo:
        compile_bundle(FIXTURES / "shared_script_param_if_misuse" / "bundle")
    _check_snapshot("shared_script_param_if_misuse", _normalize(str(excinfo.value)))


def test_shared_script_param_iteration_misuse_error_message() -> None:
    # Reviewer finding (M19 PR review): container dunders (`for`/`in`/`len`/
    # indexing) get the same specialized error, with the iteration-flavored
    # fix text (`repeat_for_each`), not the numeric/boolean one.
    from hassle.compiler import SharedScriptParamMisuseError
    from hassle.compiler.recording import recording
    from hassle.compiler.scripts import _ACTIVE_FIELDS, param

    with recording(alias="x", id="x"):
        token = _ACTIVE_FIELDS.set(frozenset({"items"}))
        try:
            marker = param("items")
            with pytest.raises(SharedScriptParamMisuseError) as excinfo:
                for _ in marker:
                    pass
        finally:
            _ACTIVE_FIELDS.reset(token)
    _check_snapshot("shared_script_param_iteration_misuse", _normalize(str(excinfo.value)))
