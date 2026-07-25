"""Golden case: the template expression builder (DESIGN §5.4).

Exercises: `state(x).value` numeric coercion, comparisons/arithmetic/boolean ops
building nested Jinja, `expr(entity_ref)` shorthand, and `template("{{ raw }}")`
passthrough. The automation's actions carry the emitted Jinja strings as plain
service-call data so the golden captures the exact compiled text.
"""

from hassle import automation, expr, service, state, template, when


@automation(id="template_demo", alias="Template expression demo")
def template_demo():
    when(state("binary_sensor.motion").to("on"))
    service(
        "notify.mobile_app",
        # comparison: numeric coercion + `>` operator
        is_hot=state("sensor.outdoor_temp").value > 25,
        # arithmetic: subtraction on a numeric expr()
        target_minus_one=expr("input_number.target_temp") - 1,
        # arithmetic then comparison (nested expression tree)
        adjusted_over_limit=(state("sensor.outdoor_temp").value + 2) > 30,
        # boolean and/or across two comparisons
        hot_and_armed=(state("sensor.outdoor_temp").value > 25)
        & (state("input_boolean.armed").value.eq("on")),
        hot_or_cold=(state("sensor.outdoor_temp").value > 30)
        | (state("sensor.outdoor_temp").value < 0),
        # boolean not
        not_armed=~(state("input_boolean.armed").value.eq("on")),
        # raw passthrough
        raw_expr=template("{{ now().hour }}"),
    )
