"""`.attr()` entity-attribute access, `var()` runtime-variable refs,
and `param()` upgraded to a composable Expr.

`.attr()` lives on entity references (EntityRef, hassle/compiler/helpers.py)
and is exposed identically through `hassle.registry.entities` (registry.py's
accessor returns the same EntityRef type) -- so `e.sun.sun.attr("elevation")`
and `EntityRef("sun", "sun").attr("elevation")` compile identically.
"""

from __future__ import annotations

from hassle.compiler.helpers import EntityRef
from hassle.compiler.templates import TemplateExpr, var
from hassle.registry import entities as e


def test_entity_ref_attr_renders_state_attr() -> None:
    ref = EntityRef("sun", "sun")
    result = ref.attr("elevation")
    assert isinstance(result, TemplateExpr)
    assert result.to_template() == "{{ state_attr('sun.sun', 'elevation') }}"


def test_registry_accessor_attr_matches_entity_ref_attr() -> None:
    # e.sun.sun.attr("elevation") -> state_attr(...) (DESIGN §5.4/§5.2 accessor).
    via_registry = e.sun.sun.attr("elevation")
    via_entity_ref = EntityRef("sun", "sun").attr("elevation")
    assert via_registry.to_template() == via_entity_ref.to_template()
    assert via_registry.to_template() == "{{ state_attr('sun.sun', 'elevation') }}"


def test_attr_composes_with_arithmetic() -> None:
    result = e.sun.sun.attr("elevation") * 2
    assert result.to_template() == "{{ state_attr('sun.sun', 'elevation') * 2 }}"


def test_attr_on_helper_declared_entity_ref() -> None:
    # Helper constructors also return EntityRef (DESIGN §5.7); `.attr()` works
    # identically there since it is the same type.
    ref = EntityRef("climate", "living")
    assert ref.attr("hvac_action").to_template() == (
        "{{ state_attr('climate.living', 'hvac_action') }}"
    )


# ---------------------------------------------------------------------------
# var() -- runtime reference to an action-level `variables:` key.
# ---------------------------------------------------------------------------


def test_var_renders_bare_name() -> None:
    result = var("wakeup_time")
    assert isinstance(result, TemplateExpr)
    assert result.to_template() == "{{ wakeup_time }}"


def test_var_composes_with_operators() -> None:
    result = var("elev") > 10
    assert result.to_template() == "{{ elev > 10 }}"


def test_var_accepts_any_name_no_declaration_check() -> None:
    # Unlike param(), variables:-block keys are freeform (no function-signature
    # binding), so var() never validates against a known set.
    assert var("anything_at_all").to_template() == "{{ anything_at_all }}"


# ---------------------------------------------------------------------------
# param() upgraded to a composable Expr (was previously usable but this pins
# the composability contract explicitly).
# ---------------------------------------------------------------------------


def test_param_is_composable_expr_inside_shared_script() -> None:
    from pathlib import Path

    from hassle.compiler import compile_bundle

    fixtures = Path(__file__).resolve().parents[3] / "fixtures" / "dsl"
    result = compile_bundle(fixtures / "shared_script_param_math" / "bundle")
    script_obj = result.objects["script:angle_calc"].to_ha()
    data = script_obj["sequence"][0]["data"]
    assert data["degrees"] == "{{ sun_angle / 360 * 2 * pi }}"
