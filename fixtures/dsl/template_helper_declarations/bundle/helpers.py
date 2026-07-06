"""Golden case: template-helper declarations (M10) for all four template
domains. The owner's driving case is `template_number` (e.g.
`number.active_hvac_zones`).

Identity (docs/ha-api-notes.md §26.6): there is no `id=`/`unique_id=` kwarg --
real HA's config flow rejects an unrecognized `unique_id` key outright.
Identity is derived from `name` (slugified): "Active HVAC Zones" ->
`template_number:active_hvac_zones`.

`template_number`/`template_select` require a write-target action sequence
(`set_value=`/`select_option=`) -- HA's form schema rejects the submission
without one (a number/select needs somewhere to send a written value; a
sensor/binary_sensor is read-only and needs only `state=`).
"""

from hassle import (
    template_binary_sensor,
    template_number,
    template_select,
    template_sensor,
)

template_number(
    name="Active HVAC Zones",
    state="{{ states.climate | selectattr('state', 'ne', 'off') | list | count }}",
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
template_sensor(
    name="Average Temp",
    state="{{ (states('sensor.a') | float + states('sensor.b') | float) / 2 }}",
    unit_of_measurement="°C",
    device_class="temperature",
)
template_binary_sensor(
    name="Any Door Open",
    state="{{ is_state('binary_sensor.front_door', 'on') }}",
    device_class="door",
)
template_select(
    name="House Scene",
    state="{{ states('input_select.house_mode') }}",
    options="{{ ['home', 'away', 'night'] }}",
    select_option={
        "action": "input_select.select_option",
        "target": {"entity_id": "input_select.house_mode"},
        "data": {"option": "{{ option }}"},
    },
)
