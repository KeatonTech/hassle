"""M2 test 4 — LibCST splice preserves the rest of the file (DESIGN §7.3).

Given a file with 3 automations + hand-written comments, splicing a new body for
the middle one must leave the other two ``def``s and all surrounding comments
byte-identical, and the spliced def must carry the
``# hassle: updated from UI on <date>`` marker (R8: the date is a parameter the
caller passes -- never wall-clock in core logic).
"""

from __future__ import annotations

from pathlib import Path

from hassle.decompiler.splice import splice_object

FIXTURE_DIR = Path(__file__).resolve().parents[3] / "fixtures" / "splice" / "three_automations"


def _read(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def test_splice_preserves_rest_of_file() -> None:
    before = _read("before.py")
    new_def = _read("new_middle_def.py")

    after = splice_object(
        before,
        object_name="middle_automation",
        new_source=new_def,
        updated_on="2026-07-03",
    )

    # The untouched defs (and their leading comments) are byte-identical substrings.
    assert (
        "# Turns on the hallway light on motion. Do not remove this comment.\n"
        '@automation(id="hall_light_on_motion", alias="Hallway: light on motion")\n'
        "def hall_light_on_motion():\n"
        "    when(state_is_on())\n"
        '    service("light.turn_on", target={"entity_id": "light.hallway"})\n'
    ) in after
    assert (
        "# Trailing comment on the porch light automation.\n"
        '@automation(id="porch_light_on_motion", alias="Porch: light on motion")\n'
        "def porch_light_on_motion():\n"
        "    when(state_is_on())\n"
        '    service("light.turn_on", target={"entity_id": "light.porch"})\n'
    ) in after
    # The local (non-hassle-object) helper function is untouched too.
    assert "def state_is_on():" in after
    assert "# a helper local to this file -- not a top-level hassle object" in after
    # Module docstring and imports are untouched.
    assert "Hand-written comments and blank lines here must survive a splice untouched." in after
    assert "from hassle import automation, service, when" in after

    # The spliced def carries the UI-update marker with the caller-supplied date.
    assert "# hassle: updated from UI on 2026-07-03" in after
    assert 'alias="Middle: edited in the UI"' in after
    assert 'alias="Middle: will be spliced"' not in after

    # Splicing is itself deterministic: no wall-clock anywhere in the call path.
    again = splice_object(
        before, object_name="middle_automation", new_source=new_def, updated_on="2026-07-03"
    )
    assert after == again


def test_splice_marker_uses_caller_supplied_date_not_wallclock() -> None:
    # R8: no wall-clock in core logic -- the marker date is whatever the caller
    # passes, not `date.today()`. A date far from "today" proves it.
    before = _read("before.py")
    new_def = _read("new_middle_def.py")

    fixed_date = "2099-01-01"
    after = splice_object(
        before, object_name="middle_automation", new_source=new_def, updated_on=fixed_date
    )
    assert f"# hassle: updated from UI on {fixed_date}" in after
    assert "# hassle: updated from UI on 2026-07-03" not in after
