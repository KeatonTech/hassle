"""M16 test 3 -- inverter coverage for the string-state vocabulary.

Both real-world spellings normalize to the DSL, then render canonically:

- `states('x') == 'y'` / `!=` / `in [...]` -> `state_of(...)` forms (byte-exact
  round-trip, I3 nice branch).
- `is_state('x', 'y')` -> `state_of('x').eq('y')` in Python source, but its
  RE-RENDER is `states('x') == 'y'`, which differs textually from the
  original `is_state(...)` call -- so the byte-exact acceptance gate
  (`invert_template`'s render-and-compare check) correctly REJECTS it and the
  caller falls back to the unchanged string form. This is the documented
  "one-time canonicalization on push" behavior (docs/DSL.md via
  docs/dsl-f3.md): only after the user's own edit (or Hassle's own compiled
  re-render) replaces the source with the canonical `states('x') == 'y'`
  spelling does it invert cleanly forever after.

The owner's real multi-line Bermuda template (`is_state(...) or
is_state(...)`) is the driving fallback case, verbatim.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hassle.compiler.bundle import compile_bundle
from hassle.compiler.template_helpers import reset_declared_template_helpers
from hassle.decompiler.codegen import decompile_object
from hassle.decompiler.template_invert import invert_template

# ---------------------------------------------------------------------------
# `states('x') == 'y'` / `!=` / `in [...]` -> state_of(...) forms.
# ---------------------------------------------------------------------------


def test_bare_states_eq_string_inverts_to_state_of_eq() -> None:
    jinja_text = "{{ states('sensor.time_of_day') == 'day' }}"
    result = invert_template(jinja_text)
    assert result is not None
    assert result.source == "state_of('sensor.time_of_day').eq('day')"


def test_bare_states_ne_string_inverts_to_state_of_ne() -> None:
    jinja_text = "{{ states('sensor.time_of_day') != 'night' }}"
    result = invert_template(jinja_text)
    assert result is not None
    assert result.source == "state_of('sensor.time_of_day').ne('night')"


def test_bare_states_in_list_inverts_to_state_of_in() -> None:
    jinja_text = "{{ states('sensor.time_of_day') in ['dawn', 'dusk'] }}"
    result = invert_template(jinja_text)
    assert result is not None
    assert result.source == "state_of('sensor.time_of_day').in_(['dawn', 'dusk'])"


@pytest.mark.parametrize(
    "jinja_text",
    [
        "{{ states('sensor.time_of_day') == 'day' }}",
        "{{ states('sensor.time_of_day') != 'night' }}",
        "{{ states('sensor.time_of_day') in ['dawn', 'dusk'] }}",
    ],
)
def test_state_of_forms_round_trip_byte_exactly_through_decorator(
    jinja_text: str, tmp_path: Path
) -> None:
    """I3 nice branch: the inverted source recompiles through the real
    `template_sensor` decorator path to the identical `state=` text."""
    result = invert_template(jinja_text)
    assert result is not None
    reset_declared_template_helpers()
    from hassle import template_sensor
    from hassle.compiler.registry import fresh

    fresh()
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "helpers.py").write_text(
        "from hassle import state_of, template_sensor\n\n"
        f"@template_sensor(name='probe')\ndef probe():\n    return {result.source}\n",
        encoding="utf-8",
    )
    compiled = compile_bundle(bundle_dir)
    obj = compiled.objects["template_sensor:probe"].to_ha()
    assert obj["state"] == jinja_text.strip()


# ---------------------------------------------------------------------------
# `is_state('x', 'y')` -> DOCUMENTED one-time-canonicalization fallback.
# ---------------------------------------------------------------------------

# The owner's real multi-line Bermuda template, verbatim (MILESTONES M16 test 3).
BERMUDA_IS_STATE_TEMPLATE = (
    "{{ is_state('sensor.keaton_watch_beacon_area', 'Living Room') or \n"
    "             is_state('sensor.keaton_phone_beacon_area', 'Living Room') }}"
)


def test_is_state_call_form_does_not_invert_cleanly() -> None:
    """`is_state(...)` re-renders as `states(...) == ...`, which differs
    textually from the original `is_state(...)` call text -- the byte-exact
    gate must reject it (fall back), NOT weaken the rule to force a match."""
    jinja_text = "{{ is_state('sensor.x', 'y') }}"
    assert invert_template(jinja_text) is None


def test_owner_bermuda_template_falls_back_cleanly() -> None:
    """The owner's real multi-line `is_state(...) or is_state(...)` template
    falls back (byte-exact gate holds) -- never raises, never silently
    produces a false-positive inversion."""
    assert invert_template(BERMUDA_IS_STATE_TEMPLATE) is None


def test_owner_bermuda_template_decompiles_to_decorator_fallback_and_round_trips(
    tmp_path: Path,
) -> None:
    """End-to-end: the gnarly (from this grammar's perspective) `is_state`
    Bermuda template decompiles to the decorator-with-raw-string fallback
    form, never raises, and round-trips byte-for-byte (I3 through the
    fallback branch) -- exactly like any other out-of-grammar template."""
    reset_declared_template_helpers()
    from hassle import template_sensor
    from hassle.compiler.registry import fresh

    fresh()
    template_sensor(name="Beacon Area Combined", state=BERMUDA_IS_STATE_TEMPLATE)
    from hassle.compiler.registry import current_registry

    prebuilt = current_registry().prebuilt
    obj = next(
        p.obj for p in prebuilt if p.obj.object_key() == "template_sensor:beacon_area_combined"
    )
    source = decompile_object("template_sensor:beacon_area_combined", obj)
    assert source.startswith("@template_sensor(")
    assert "return " in source
    decorator_line = source.split("\n", 1)[0]
    assert "state=" not in decorator_line

    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "helpers.py").write_text(
        "from hassle import template_sensor\n\n" + source, encoding="utf-8"
    )
    recompiled = compile_bundle(bundle_dir)
    assert (
        recompiled.objects["template_sensor:beacon_area_combined"].to_ha()["state"]
        == BERMUDA_IS_STATE_TEMPLATE
    )


def test_hand_converted_canonical_form_round_trips_as_python() -> None:
    """After the user converts the Bermuda template by hand (or pushes any
    edit) to the canonical `state_of(...).eq(...) | state_of(...).eq(...)`
    spelling, it inverts and re-renders byte-exactly forever after."""
    canonical = (
        "{{ (states('sensor.keaton_watch_beacon_area') == 'Living Room') or "
        "(states('sensor.keaton_phone_beacon_area') == 'Living Room') }}"
    )
    result = invert_template(canonical)
    assert result is not None
    assert result.source == (
        "(state_of('sensor.keaton_watch_beacon_area').eq('Living Room') | "
        "state_of('sensor.keaton_phone_beacon_area').eq('Living Room'))"
    )
