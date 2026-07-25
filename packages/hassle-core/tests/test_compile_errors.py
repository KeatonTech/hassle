"""Trap-catching + compile error snapshots.

Error messages are product surface: each states *what*, *where* (file:line), and
*the fix*, in one paragraph, and is snapshot-tested. Snapshots live under
``tests/snapshots/errors/`` and change only with a visible diff.

Covered here (the core-compiler subset — the full trap family incl. the
`raw_automation` non-JSON case belongs to the templates/actions builders):
  - `CompileTimeBranchError` from `__bool__` on a state/condition expression,
    naming file:line and showing the `with if_then(...)` rewrite hint.
  - duplicate id across a bundle.
  - unknown @automation option.
  - a DSL call made outside any recording context.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hassle import state
from hassle.compiler import (
    CompileTimeBranchError,
    DuplicateObjectError,
    NoRecordingContextError,
    UnknownAutomationOptionError,
    compile_bundle,
)
from hassle.compiler.recording import recording, when
from hassle_dev.snapshots import check_snapshot, normalize_error

SNAP_DIR = Path(__file__).resolve().parent / "snapshots" / "errors"


def _check_snapshot(name: str, actual: str) -> None:
    check_snapshot(SNAP_DIR, name, actual)


def _normalize(msg: str) -> str:
    return normalize_error(msg, mask_lines_for=Path(__file__).name)


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
            # Native Python `if` on a runtime state expression must trap (§5.5).
            if expr:
                _ = 1
    msg = str(excinfo.value)
    assert "if_then" in msg  # the rewrite hint
    assert "test_compile_errors.py" in msg  # where (file)


def test_duplicate_id_error_message() -> None:
    case = Path(__file__).resolve().parents[3] / "fixtures" / "dsl" / "duplicate_id" / "bundle"
    with pytest.raises(DuplicateObjectError) as excinfo:
        compile_bundle(case)
    _check_snapshot("duplicate_id", _normalize(str(excinfo.value)))


def test_unknown_automation_option_message() -> None:
    from hassle.compiler import automation

    with pytest.raises(UnknownAutomationOptionError) as excinfo:

        @automation(alias="x", id="x", flibbertigibbet=1)
        def _bad() -> None:
            pass

    _check_snapshot("unknown_option", _normalize(str(excinfo.value)))


def test_dsl_call_outside_context_message() -> None:
    with pytest.raises(NoRecordingContextError) as excinfo:
        when(state("binary_sensor.motion").to("on"))
    _check_snapshot("no_context", _normalize(str(excinfo.value)))


def test_duplicate_id_error_names_reconcile_flow_when_one_site_is_a_ui_splice(
    tmp_path: Path,
) -> None:
    """A loop-splice reconcile (a metaprogrammed object's
    UI edit got appended under the `# hassle: updated from UI on <date>`
    marker -- see `SplicingSourceWriter.splice_object`'s append path) produces
    a DuplicateObjectError the next time the bundle compiles, because the
    original loop-generated def AND the appended standalone def both now
    declare the same id. When one of the two conflicting declaration sites is
    preceded by that marker, the message must point at the reconcile flow (fold
    into the loop / extract the object / delete the appended block), on top of
    the existing "name both sites" text."""
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "rooms.py").write_text(
        '"""Loop-generated automations."""\n'
        "from hassle import automation, service, state, when\n\n"
        'ROOMS = ["kitchen", "office"]\n\n'
        "for room in ROOMS:\n\n"
        '    @automation(id=f"motion_{room}", alias=f"Motion light: {room}")\n'
        "    def _motion(room: str = room):\n"
        '        when(state(f"binary_sensor.{room}_motion").to("on"))\n'
        '        service("light.turn_on", entity_id=f"light.{room}")\n\n\n'
        "# hassle: updated from UI on 2026-07-05\n"
        '@automation(id="motion_kitchen", alias="Motion light: kitchen (UI edit)")\n'
        "def motion_kitchen_ui_edit():\n"
        '    when(state("binary_sensor.kitchen_motion").to("on"))\n'
        '    service("light.turn_on", entity_id="light.kitchen")\n'
        '    service("light.turn_on", entity_id="light.extra")\n',
        encoding="utf-8",
    )

    with pytest.raises(DuplicateObjectError) as excinfo:
        compile_bundle(bundle)
    msg = str(excinfo.value)
    assert "automation:motion_kitchen" in msg
    # The reconcile-flow sentence: names the metaprogramming/append situation
    # and the three fix options, plus re-running validate.
    lowered = msg.lower()
    assert "generated by metaprogramming" in lowered or "generated by a loop" in lowered
    assert "fold into the loop" in lowered or "fold" in lowered
    assert "extract" in lowered
    assert "delete" in lowered
    assert "validate" in lowered
