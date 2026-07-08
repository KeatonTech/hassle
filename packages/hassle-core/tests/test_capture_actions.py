"""Public capture seam (task #30, `ux/capture-notify-recipe`): `capture_actions()` /
`emit_actions(...)` -- the minimal public pair that lets a `lib/` builder capture a
`with`-block's actions and splice them into an action container it builds itself
(DESIGN §5.6 macro/lib pattern), without reaching into the internal
`Recorder.push_actions`/`RecordedNode`/`_require_active` seam that `if_then`/`choose`
are built on (docs/m1-internal-api.md §2).

`capture_actions()` is a context manager yielding a list of plain action-body dicts
(the same shape `service(...)`/`if_then(...)`/etc. append to `rec.actions` today,
minus the `RecordedNode` span wrapper -- spans are compiler-internal). `emit_actions`
re-splices previously captured bodies into the CURRENT recording context, re-wrapped
with a span captured at the `emit_actions(...)` call site (so errors ever raised
against the emitted actions point at the caller's line, never leak `RecordedNode`).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from hassle import service, when
from hassle.compiler import NoRecordingContextError, capture_actions, emit_actions
from hassle.compiler.bundle import compile_registered
from hassle.compiler.recording import recording
from hassle.compiler.registry import fresh

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


def test_capture_actions_yields_plain_action_body_dicts() -> None:
    with recording(alias="x", id="x"):
        with capture_actions() as bodies:
            service("light.turn_on", entity_id="light.a")
            service("light.turn_off", entity_id="light.b")
        assert bodies == [
            {"action": "light.turn_on", "data": {"entity_id": "light.a"}},
            {"action": "light.turn_off", "data": {"entity_id": "light.b"}},
        ]


def test_capture_actions_does_not_leak_into_enclosing_sequence() -> None:
    # Actions recorded inside `with capture_actions():` land ONLY in the yielded
    # list -- they must not also show up in the enclosing automation's own
    # top-level action sequence (the whole point of a capture seam: the caller
    # decides where/whether the captured bodies end up, via `emit_actions`).
    with recording(alias="x", id="x") as rec:
        with capture_actions():
            service("light.turn_on", entity_id="light.a")
        assert rec.actions == []


def test_emit_actions_splices_into_current_sequence() -> None:
    with recording(alias="x", id="x") as rec:
        with capture_actions() as bodies:
            service("light.turn_on", entity_id="light.a")
        service("light.turn_off", entity_id="light.b")  # a normal action in between
        emit_actions(bodies)
        assert [n.body for n in rec.actions] == [
            {"action": "light.turn_off", "data": {"entity_id": "light.b"}},
            {"action": "light.turn_on", "data": {"entity_id": "light.a"}},
        ]


def test_emit_actions_can_replay_captured_bodies_more_than_once() -> None:
    # A `lib/` recipe builder captures a block once but may splice it into more
    # than one branch (e.g. two `choose()` branches sharing a notification
    # action list) -- `emit_actions` must not mutate/consume `bodies`.
    with recording(alias="x", id="x") as rec:
        with capture_actions() as bodies:
            service("light.turn_on", entity_id="light.a")
        emit_actions(bodies)
        emit_actions(bodies)
        assert len(rec.actions) == 2
        assert rec.actions[0].body == rec.actions[1].body
        assert rec.actions[0].body == {"action": "light.turn_on", "data": {"entity_id": "light.a"}}


def test_emit_actions_respects_nested_push_actions_target() -> None:
    # `emit_actions` must append to `rec.current_actions` (the active nested
    # target, e.g. inside a `with if_then(...):` body) not always `rec.actions`.
    from hassle.compiler.conditions import trigger_condition
    from hassle.compiler.control_flow import if_then

    with recording(alias="x", id="x") as rec:
        with capture_actions() as bodies:
            service("light.turn_on", entity_id="light.a")
        with if_then(trigger_condition("t")):
            emit_actions(bodies)
        assert rec.actions[-1].body["then"] == [
            {"action": "light.turn_on", "data": {"entity_id": "light.a"}}
        ]


def test_capture_actions_outside_recording_context_raises() -> None:
    with pytest.raises(NoRecordingContextError) as excinfo, capture_actions():
        pass
    _check_snapshot("capture_actions_no_context", _normalize(str(excinfo.value)))


def test_emit_actions_outside_recording_context_raises() -> None:
    with pytest.raises(NoRecordingContextError) as excinfo:
        emit_actions([{"action": "light.turn_on"}])
    _check_snapshot("emit_actions_no_context", _normalize(str(excinfo.value)))


def test_capture_actions_composes_into_a_real_compiled_automation() -> None:
    # End-to-end: a `lib/`-style helper that captures a block and emits it
    # inside a `choose()` branch, exercised through the real compile pipeline
    # (not just the recording layer) -- proves `capture_actions`/`emit_actions`
    # are usable as the seam a genuine cookbook recipe builds on.
    from hassle import automation, choose, state
    from hassle.compiler.registry import current_registry

    fresh()

    @automation(id="capture_demo", alias="capture demo")
    def _demo() -> None:
        when(state("button.start").to("on"))
        with capture_actions() as bodies:
            service("light.turn_on", entity_id="light.a")
        with choose() as c, c.when_(state("binary_sensor.door").is_("on")):
            emit_actions(bodies)

    reg = current_registry()
    result = compile_registered(list(reg.objects), list(reg.prebuilt))
    obj = result.objects["automation:capture_demo"]
    actions = obj.actions  # type: ignore[attr-defined]
    assert actions == [
        {
            "choose": [
                {
                    "conditions": [
                        {
                            "condition": "state",
                            "entity_id": "binary_sensor.door",
                            "state": "on",
                        }
                    ],
                    "sequence": [{"action": "light.turn_on", "data": {"entity_id": "light.a"}}],
                }
            ]
        }
    ]
    fresh()
