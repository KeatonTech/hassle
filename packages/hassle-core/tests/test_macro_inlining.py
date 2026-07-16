"""M1 test 2 — `@macro` compile-time inlining (DESIGN §5.6).

A macro is an ordinary Python function decorated with `@macro`; calling it
inside an `@automation`/`@script` body splices its recorded actions into the
caller's action list, with zero HA-side footprint of its own (no separate
compiled object). Covers: used by two automations (both get the expansion),
nested macros, macros with args, and the outside-context error.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hassle.compiler import NoRecordingContextError, compile_bundle

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "dsl"


def test_macro_used_by_two_automations_both_get_expansion() -> None:
    result = compile_bundle(FIXTURES / "macro_two_callers" / "bundle")
    front = result.objects["automation:front_door"].to_ha()
    back = result.objects["automation:back_door"].to_ha()

    # Both automations contain the full macro expansion (two notify calls).
    front_actions = [a["action"] for a in front["actions"]]
    back_actions = [a["action"] for a in back["actions"]]
    assert front_actions == ["notify.mobile_app_kai", "notify.mobile_app_spouse"]
    assert back_actions == [
        "notify.mobile_app_kai",
        "notify.mobile_app_spouse",
        "light.turn_on",
    ]
    # Each caller's own message argument reaches its own expansion (not shared
    # mutable state between the two calls).
    assert front["actions"][0]["data"]["message"] == "Front door opened"
    assert back["actions"][0]["data"]["message"] == "Back door opened"

    # The macro itself never becomes its own compiled object.
    assert "automation:notify_adults" not in result.objects
    assert not any(k.startswith("script:") for k in result.objects)


def test_nested_macros_fully_inline() -> None:
    result = compile_bundle(FIXTURES / "macro_nested" / "bundle")
    obj = result.objects["automation:arrival"].to_ha()
    actions = [a["action"] for a in obj["actions"]]
    # welcome_home() -> flash_porch() (2 actions) + its own notify (1 action).
    assert actions == ["light.turn_on", "light.turn_off", "notify.mobile_app_kai"]


def test_macro_with_compile_time_args_unrolls() -> None:
    result = compile_bundle(FIXTURES / "macro_with_args" / "bundle")
    obj = result.objects["automation:alert"].to_ha()
    actions = [a["action"] for a in obj["actions"]]
    # times=3 -> 3 pairs of (turn_on, turn_off), unrolled at compile time.
    assert actions == ["light.turn_on", "light.turn_off"] * 3


def test_macro_called_outside_recording_context_raises() -> None:
    case = FIXTURES / "macro_outside_context" / "bundle"
    with pytest.raises(NoRecordingContextError) as excinfo:
        compile_bundle(case)
    message = str(excinfo.value)
    assert "macro notify_all()" in message
    assert "bad.py:12" in message
