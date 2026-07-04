"""M1 test 6 — every recorded trigger/condition/action carries file:line.

Spans are captured by frame inspection at record time and ride on IR nodes as
non-serialized metadata: they map an IR node back to the DSL call that produced
it, but MUST NOT appear in ``to_ha()`` output (that would break I3/hashing).
"""

from __future__ import annotations

from pathlib import Path

from hassle_core.compiler import compile_bundle

CASE = Path(__file__).resolve().parents[3] / "fixtures" / "dsl" / "state_delay_service"


def test_spans_point_at_dsl_call_lines() -> None:
    result = compile_bundle(CASE / "bundle")
    obj = result.objects["automation:hall_light_on_motion"]

    # hallway.py: when() @ line 12, service turn_on @ 13, delay @ 14, turn_off @ 15.
    src = "hallway.py"
    trig_spans = result.spans_for(obj, "triggers")
    assert len(trig_spans) == 1
    assert trig_spans[0].file.endswith(src)
    assert trig_spans[0].line == 12

    action_spans = result.spans_for(obj, "actions")
    assert [s.line for s in action_spans] == [13, 14, 15]
    assert all(s.file.endswith(src) for s in action_spans)


def test_spans_do_not_leak_into_to_ha() -> None:
    result = compile_bundle(CASE / "bundle")
    obj = result.objects["automation:hall_light_on_motion"]
    ha = obj.to_ha()
    blob = repr(ha)
    # No span keys and no source file paths anywhere in the serialized body.
    assert "span" not in blob
    assert ".py" not in blob
    for trig in ha["triggers"]:
        assert "__span__" not in trig
    for act in ha["actions"]:
        assert "__span__" not in act
