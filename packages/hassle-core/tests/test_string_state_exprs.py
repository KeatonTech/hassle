"""String-state expression vocabulary (DESIGN §5.4 extension).

`state_of(entity_or_id)` is a bare string-context template read (mirrors
`expr()`'s numeric-context read exactly, minus the `| float` filter); string
comparisons are spelled via the existing `.eq()`/`.ne()` methods, and
membership via the new `.in_([...])`. Boolean composition (`&`/`|`/`~`) and
the `__bool__`/`CompileTimeBranchError` trap are unchanged -- `state_of(...)`
just produces another `TemplateExpr`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hassle.compiler import CompileTimeBranchError, compile_bundle
from hassle.compiler.builders import state
from hassle.compiler.templates import TemplateEntityRefError, TemplateExpr, state_of
from hassle.registry import entities as e

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "dsl"


# ---------------------------------------------------------------------------
# Test 1: state_of(...).eq(...) exact rendering + composition/precedence +
# accepted argument shapes (e.-ref and plain string, mirroring expr()).
# ---------------------------------------------------------------------------


def test_state_of_eq_renders_exact_jinja() -> None:
    result = state_of("sensor.x").eq("Living Room")
    assert result.to_template() == "{{ states('sensor.x') == 'Living Room' }}"


def test_state_of_bare_read_renders_states_call_only() -> None:
    result = state_of("sensor.x")
    assert result.to_template() == "{{ states('sensor.x') }}"


def test_state_of_ne_renders_exact_jinja() -> None:
    result = state_of("sensor.x").ne("Living Room")
    assert result.to_template() == "{{ states('sensor.x') != 'Living Room' }}"


def test_state_of_in_renders_list_literal() -> None:
    result = state_of("sensor.x").in_(["a", "b"])
    assert result.to_template() == "{{ states('sensor.x') in ['a', 'b'] }}"


def test_state_of_accepts_plain_entity_id_string() -> None:
    result = state_of("sensor.time_of_day").eq("day")
    assert result.to_template() == "{{ states('sensor.time_of_day') == 'day' }}"


def test_state_of_accepts_e_registry_ref() -> None:
    # Mirrors expr()'s argument handling exactly: an `e.`-registry ref
    # extracts the same `domain.object_id` string a plain string would.
    result = state_of(e.sensor.time_of_day).eq("day")
    assert result.to_template() == "{{ states('sensor.time_of_day') == 'day' }}"


def test_state_of_accepts_state_builder() -> None:
    # expr()/`.value` accept a `state(...)` builder too (built from one
    # entity id); state_of() mirrors that same coercion path.
    result = state_of(state("sensor.time_of_day")).eq("day")
    assert result.to_template() == "{{ states('sensor.time_of_day') == 'day' }}"


def test_boolean_composition_parenthesization_matches_renderer_rules() -> None:
    a = state_of("sensor.time_of_day").eq("day")
    b = state_of("sensor.time_of_day").eq("dawn")
    assert (a & b).to_template() == (
        "{{ (states('sensor.time_of_day') == 'day') and (states('sensor.time_of_day') == 'dawn') }}"
    )
    assert (a | b).to_template() == (
        "{{ (states('sensor.time_of_day') == 'day') or (states('sensor.time_of_day') == 'dawn') }}"
    )
    assert (~a).to_template() == "{{ not (states('sensor.time_of_day') == 'day') }}"


def test_state_of_result_traps_python_if() -> None:
    result = state_of("sensor.x").eq("y")
    assert isinstance(result, TemplateExpr)
    with pytest.raises(CompileTimeBranchError):
        if result:
            pass


def test_state_of_bare_read_is_a_str_and_serializes_natively() -> None:
    import json

    result = state_of("sensor.x")
    assert isinstance(result, str)
    assert json.dumps({"v": result}) == json.dumps({"v": str(result)})


# ---------------------------------------------------------------------------
# Custom-function composition -> golden pair.
# ---------------------------------------------------------------------------


def test_custom_function_composition_golden_bundle() -> None:
    """A plain Python function returning `state_of(...).eq(...)`, composed
    with `|`, used as a `@template_binary_sensor` body -- compiles to the
    exact expected template."""
    result = compile_bundle(FIXTURES / "beacon_area_composition" / "bundle")
    obj = result.objects["template_binary_sensor:kai_home_beacon"].to_ha()
    assert obj["state"] == (
        "{{ (states('sensor.kai_watch_beacon_area') == 'Living Room') or "
        "(states('sensor.kai_phone_beacon_area') == 'Living Room') }}"
    )


def test_state_of_string_golden_bundle() -> None:
    result = compile_bundle(FIXTURES / "state_of_string_golden" / "bundle")
    obj = result.objects["automation:string_state_demo"].to_ha()
    data = obj["actions"][0]["data"]
    assert data["raw_state"] == "{{ states('sensor.time_of_day') }}"
    assert data["is_daytime"] == "{{ states('sensor.time_of_day') == 'day' }}"
    assert data["is_not_night"] == "{{ states('sensor.time_of_day') != 'night' }}"
    assert data["is_transition"] == "{{ states('sensor.time_of_day') in ['dawn', 'dusk'] }}"
    assert data["is_daytime_via_ref"] == "{{ states('sensor.time_of_day') == 'day' }}"
    assert data["day_and_hot"] == (
        "{{ (states('sensor.time_of_day') == 'day') and "
        "(states('sensor.outdoor_temp') | float > 25) }}"
    )
    assert data["dawn_or_dusk"] == (
        "{{ (states('sensor.time_of_day') == 'dawn') or (states('sensor.time_of_day') == 'dusk') }}"
    )
    assert data["not_night"] == "{{ not (states('sensor.time_of_day') == 'night') }}"


# ---------------------------------------------------------------------------
# Error surface -- `.eq()` against a non-literal/non-expr, or
# `state_of()` on a non-entity arg -> compile error stating what/where/fix,
# snapshot-tested (see test_string_state_errors.py for the snapshot
# assertions themselves; these confirm the raised type + reused
# TemplateEntityRefError class).
# ---------------------------------------------------------------------------


def test_state_of_on_list_valued_state_raises_entity_ref_error() -> None:
    with pytest.raises(TemplateEntityRefError):
        state_of(state(["light.a", "light.b"]))


def test_state_of_on_non_entity_value_raises_entity_ref_error() -> None:
    with pytest.raises(TemplateEntityRefError):
        state_of(123)  # type: ignore[arg-type]
