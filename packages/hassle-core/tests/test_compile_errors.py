"""M1 test 5 (core subset) — trap-catching + compile error snapshots (R6).

Error messages are product surface: each states *what*, *where* (file:line), and
*the fix*, in one paragraph, and is snapshot-tested. Snapshots live under
``tests/snapshots/errors/`` and change only with a visible diff.

Covered here (the M1-core subset — the full trap family incl. the `raw_automation`
non-JSON case belongs to the templates/actions workstreams):
  - `CompileTimeBranchError` from `__bool__` on a state/condition expression,
    naming file:line and showing the `with if_then(...)` rewrite hint.
  - duplicate id across a bundle.
  - unknown @automation option.
  - a DSL call made outside any recording context.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from hassle_core.compiler import (
    CompileTimeBranchError,
    DuplicateObjectError,
    NoRecordingContextError,
    UnknownAutomationOptionError,
    compile_bundle,
)
from hassle_core.compiler.recording import recording, when
from hassle_core.dsl_builtins import state

SNAP_DIR = Path(__file__).resolve().parent / "snapshots" / "errors"


def _check_snapshot(name: str, actual: str) -> None:
    """Compare against a stored snapshot; write it if HASSLE_UPDATE_SNAPSHOTS is set."""
    import os

    path = SNAP_DIR / f"{name}.txt"
    if os.environ.get("HASSLE_UPDATE_SNAPSHOTS"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual + "\n", encoding="utf-8")
    assert path.is_file(), f"missing snapshot {path}; set HASSLE_UPDATE_SNAPSHOTS=1 to write it"
    assert actual == path.read_text(encoding="utf-8").rstrip("\n")


def _normalize(msg: str) -> str:
    """Replace absolute paths with a stable basename so snapshots are portable."""
    return re.sub(r"(/[^\s:]+/)([^/\s:]+\.py)", r"\2", msg)


def test_compile_time_branch_error_message() -> None:
    with recording(alias="x", id="x"):
        expr = state("binary_sensor.motion").is_("on")
        with pytest.raises(CompileTimeBranchError) as excinfo:
            # A native Python `if` on a runtime state comparison must fail loudly.
            bool(expr)
    _check_snapshot("compile_time_branch", _normalize(str(excinfo.value)))


def test_compile_time_branch_error_has_location_and_fix() -> None:
    with recording(alias="x", id="x"):
        expr = state("light.hallway").is_("on")
        with pytest.raises(CompileTimeBranchError) as excinfo:
            if expr:  # noqa: SIM103  (intentional: triggers __bool__)
                pass
    msg = str(excinfo.value)
    assert "if_then" in msg  # the rewrite hint
    assert "test_compile_errors.py" in msg  # where (file)


def test_duplicate_id_error_message() -> None:
    case = Path(__file__).resolve().parents[3] / "fixtures" / "dsl" / "duplicate_id" / "bundle"
    with pytest.raises(DuplicateObjectError) as excinfo:
        compile_bundle(case)
    _check_snapshot("duplicate_id", _normalize(str(excinfo.value)))


def test_unknown_automation_option_message() -> None:
    from hassle_core.compiler.recording import automation

    with pytest.raises(UnknownAutomationOptionError) as excinfo:

        @automation(alias="x", id="x", flibbertigibbet=1)
        def _bad() -> None:
            pass

    _check_snapshot("unknown_option", _normalize(str(excinfo.value)))


def test_dsl_call_outside_context_message() -> None:
    with pytest.raises(NoRecordingContextError) as excinfo:
        when(state("binary_sensor.motion").to("on"))
    _check_snapshot("no_context", _normalize(str(excinfo.value)))
