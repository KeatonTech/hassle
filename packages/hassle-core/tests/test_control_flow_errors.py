"""M1 actions/control-flow error coverage (R6: what/where/fix, snapshot-tested).

Covers `ElseWithoutIfError` -- `with else_then():`/`with else_if(...):` used
where the immediately-preceding action in the current list is not an
`if_then`/`choose` container. This is the actions/control-flow workstream's
own error class (docs/m1-internal-api.md §5), added alongside the M1-core
errors in `hassle_core/compiler/errors.py`.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from hassle_core.compiler import ElseWithoutIfError
from hassle_core.compiler.control_flow import else_if, else_then, if_then
from hassle_core.compiler.recording import recording
from hassle_core.dsl_builtins import service, state

SNAP_DIR = Path(__file__).resolve().parent / "snapshots" / "errors"


def _check_snapshot(name: str, actual: str) -> None:
    path = SNAP_DIR / f"{name}.txt"
    if os.environ.get("HASSLE_UPDATE_SNAPSHOTS"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual + "\n", encoding="utf-8")
    assert path.is_file(), f"missing snapshot {path}; set HASSLE_UPDATE_SNAPSHOTS=1 to write it"
    assert actual == path.read_text(encoding="utf-8").rstrip("\n")


def _normalize(msg: str) -> str:
    return re.sub(r"(/[^\s:]+/)([^/\s:]+\.py)", r"\2", msg)


def test_else_then_without_preceding_if_message() -> None:
    with recording(alias="x", id="x"), pytest.raises(ElseWithoutIfError) as excinfo:
        service("light.turn_on", entity_id="light.a")
        with else_then():
            service("light.turn_off", entity_id="light.a")
    _check_snapshot("else_without_if", _normalize(str(excinfo.value)))


def test_else_then_without_preceding_if_has_location_and_fix() -> None:
    with (
        recording(alias="x", id="x"),
        pytest.raises(ElseWithoutIfError) as excinfo,
        else_then(),
    ):
        pass
    msg = str(excinfo.value)
    assert "test_control_flow_errors.py" in msg  # where (file)
    assert "if_then" in msg or "choose" in msg  # the fix hint


def test_else_then_twice_in_a_row_traps() -> None:
    # The second `else_then()` no longer has an `if`/`choose` immediately
    # before it (the first `else_then` filled the slot and is itself not an
    # if/choose container), so it must trap rather than silently overwrite.
    with recording(alias="x", id="x"), pytest.raises(ElseWithoutIfError):
        with if_then(state("light.a").is_("on")):
            service("light.turn_on", entity_id="light.b")
        with else_then():
            service("light.turn_off", entity_id="light.b")
        with else_then():
            service("light.turn_off", entity_id="light.c")


def test_else_if_without_preceding_if_traps() -> None:
    with recording(alias="x", id="x"), pytest.raises(ElseWithoutIfError):
        service("light.turn_on", entity_id="light.a")
        with else_if(state("light.a").is_("on")):
            service("light.turn_off", entity_id="light.a")


def test_else_if_after_else_then_traps() -> None:
    # Once `else_then` has filled the `default`/`else` slot, a subsequent
    # `else_if` must trap too -- the slot is one-shot regardless of which
    # trailing construct tries to refill it.
    with recording(alias="x", id="x"), pytest.raises(ElseWithoutIfError):
        with if_then(state("light.a").is_("on")):
            service("light.turn_on", entity_id="light.b")
        with else_then():
            service("light.turn_off", entity_id="light.b")
        with else_if(state("light.a").is_("off")):
            service("light.turn_off", entity_id="light.c")
