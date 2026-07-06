"""Golden case: template-helper declarations via the DECORATOR form (M13).

For all four template domains, `state=` (and `template_select`'s `options=`)
is spelled as a decorated zero-arg function returning a `TemplateExpr` (the
M1.1 `hassle.compiler.math_expr`/`templates` python->Jinja surface) instead
of a raw Jinja string. The decorator form compiles to the IDENTICAL IR body
as the equivalent call form (M13 test 1) -- `state=`/`options=` become the
rendered Jinja, byte-identical to hand-writing the same Jinja string.

Function names are cosmetic (derived from `slug(name)`, like automations'
function names) -- identity remains `slug(name)`.
"""

from hassle import (
    expr,
    state,
    template_binary_sensor,
    template_number,
    template_select,
    template_sensor,
)
from hassle.registry import entities as e


@template_number(
    name="Active HVAC Zones",
    set_value={
        "action": "input_number.set_value",
        "target": {"entity_id": "input_number.hvac_zone_override"},
        "data": {"value": "{{ value }}"},
    },
    min=0,
    max=8,
    step=1,
    unit_of_measurement="zones",
)
def active_hvac_zones():
    return expr(e.input_number.hvac_zone_override)


@template_sensor(
    name="Average Temp",
    unit_of_measurement="°C",
    device_class="temperature",
)
def average_temp():
    return (expr(e.sensor.a) + expr(e.sensor.b)) / 2


@template_binary_sensor(
    name="Any Door Open",
    device_class="door",
)
def any_door_open():
    return state(e.binary_sensor.front_door).value > 0


@template_select(
    name="House Scene",
    select_option={
        "action": "input_select.select_option",
        "target": {"entity_id": "input_select.house_mode"},
        "data": {"option": "{{ option }}"},
    },
)
def house_scene():
    return expr(e.input_select.house_mode)
