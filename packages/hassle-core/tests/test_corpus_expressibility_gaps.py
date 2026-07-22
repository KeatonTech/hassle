"""Goldens closing expressibility gaps: fixture shapes with no backing golden
even though the DSL could express them.

- standalone ``@script`` objects (script_basic / script_mode_queued /
  script_with_fields) — the only script golden was ``shared_script_call``;
- a purpose trigger with a renamed pre-2026.7 key (``battery.low``) passed
  through verbatim;
- a scalar/string ``delay`` shape, which the ergonomic ``delay()`` cannot emit
  but ``raw_action`` expresses faithfully (the raw escape hatch backstop).

These tests pin those shapes so the corpus is fully covered.
"""

from __future__ import annotations

from pathlib import Path

from hassle.compiler import compile_bundle
from hassle.compiler.raw import raw_action
from hassle.compiler.recording import recording

_DSL = Path(__file__).resolve().parents[3] / "fixtures" / "dsl"


def test_standalone_scripts_compile() -> None:
    objects = {
        k: o.to_ha()
        for k, o in compile_bundle(_DSL / "standalone_scripts" / "bundle").objects.items()
    }
    assert set(objects) == {
        "script:basic_greet",
        "script:queued_worker",
        "script:script_with_fields",
    }
    # queued mode + max are plain passthrough options
    assert objects["script:queued_worker"]["mode"] == "queued"
    assert objects["script:queued_worker"]["max"] == 10
    # full field metadata (name/description/example/default) is authored via fields=
    fields = objects["script:script_with_fields"]["fields"]
    assert fields["brightness"] == {
        "name": "Brightness",
        "description": "Brightness level 0-255",
        "example": 200,
        "default": 255,
    }


def test_renamed_purpose_key_passes_through() -> None:
    objects = compile_bundle(_DSL / "purpose_trigger_renamed_key" / "bundle").objects
    (auto,) = objects.values()
    body = auto.to_ha()
    # The legacy type string is neither rejected nor rewritten by the compiler.
    assert body["triggers"][0]["trigger"] == "battery.low"
    assert body["triggers"][0]["target"] == {"entity_id": "sensor.wireless_device_battery"}


def test_string_delay_expressible_via_raw_action() -> None:
    # delay() only emits dict form; the corpus's "HH:MM:SS"/scalar delay shapes
    # (automation_delay_hh_mm_ss / automation_delay_numeric / mixed_key_order)
    # are expressed with raw_action, the raw escape hatch backstop.
    with recording(kind="automation", id="x") as rec:
        raw_action({"delay": "00:05:30"})
        raw_action({"delay": 30})
    assert [n.body for n in rec.actions] == [{"delay": "00:05:30"}, {"delay": 30}]
