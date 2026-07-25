"""Template expression builder -> exact Jinja strings (DESIGN §5.4).

Operator overloading on `state(x).value` / `expr(x)` builds nested Jinja
expressions; the DESIGN §5.4 examples are normative and asserted verbatim here
(byte-exact), plus the full golden automation via `compile_bundle`. Comparison
results inherit the `CompileTimeBranchError` `__bool__` trap (DESIGN §5.5).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hassle.compiler import CompileTimeBranchError, compile_bundle
from hassle.compiler.builders import state
from hassle.compiler.templates import TemplateExpr, expr, template

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "dsl"


def test_design_5_4_state_value_comparison_example() -> None:
    # state(e.sensor.outdoor_temp).value > 25
    # -> {{ states('sensor.outdoor_temp') | float > 25 }}
    result = state("sensor.outdoor_temp").value > 25
    assert result.to_template() == "{{ states('sensor.outdoor_temp') | float > 25 }}"


def test_design_5_4_expr_subtraction_example() -> None:
    # expr(e.input_number.target_temp) - 1
    # -> "{{ states('input_number.target_temp') | float - 1 }}"
    result = expr("input_number.target_temp") - 1
    assert str(result) == "{{ states('input_number.target_temp') | float - 1 }}"


def test_template_raw_passthrough() -> None:
    result = template("{{ now().hour }}")
    assert result.to_template() == "{{ now().hour }}"


def test_template_expr_is_a_str_and_serializes_natively() -> None:
    import json

    result = expr("sensor.x") > 10
    assert isinstance(result, str)
    assert json.dumps({"v": result}) == json.dumps({"v": str(result)})


def test_boolean_and_or_not_operators() -> None:
    a = state("sensor.outdoor_temp").value > 25
    b = state("input_boolean.armed").value.eq("on")
    assert (a & b).to_template() == (
        "{{ (states('sensor.outdoor_temp') | float > 25) and "
        "(states('input_boolean.armed') | float == 'on') }}"
    )
    assert (a | b).to_template() == (
        "{{ (states('sensor.outdoor_temp') | float > 25) or "
        "(states('input_boolean.armed') | float == 'on') }}"
    )
    assert (~a).to_template() == "{{ not (states('sensor.outdoor_temp') | float > 25) }}"


def test_comparison_result_traps_python_if() -> None:
    result = state("sensor.outdoor_temp").value > 25
    assert isinstance(result, TemplateExpr)
    with pytest.raises(CompileTimeBranchError):
        if result:
            pass


def test_comparison_result_traps_bool() -> None:
    result = expr("sensor.x") > 10
    with pytest.raises(CompileTimeBranchError):
        bool(result)


def test_template_expr_golden_bundle() -> None:
    result = compile_bundle(FIXTURES / "template_expr_golden" / "bundle")
    obj = result.objects["automation:template_demo"].to_ha()
    data = obj["actions"][0]["data"]
    assert data["is_hot"] == "{{ states('sensor.outdoor_temp') | float > 25 }}"
    assert data["target_minus_one"] == "{{ states('input_number.target_temp') | float - 1 }}"
    assert data["raw_expr"] == "{{ now().hour }}"
