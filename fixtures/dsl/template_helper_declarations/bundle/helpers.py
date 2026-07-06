"""Golden case: template-helper declarations (M10) for all four template
domains. The owner's driving case is `template_number` (e.g.
`number.active_hvac_zones`).
"""

from hassle import (
    template_binary_sensor,
    template_number,
    template_select,
    template_sensor,
)

template_number(
    id="active_hvac_zones",
    name="Active HVAC Zones",
    state="{{ states.climate | selectattr('state', 'ne', 'off') | list | count }}",
    min=0,
    max=8,
    step=1,
    unit_of_measurement="zones",
)
template_sensor(
    id="average_temp",
    name="Average Temp",
    state="{{ (states('sensor.a') | float + states('sensor.b') | float) / 2 }}",
    unit_of_measurement="°C",
    device_class="temperature",
)
template_binary_sensor(
    id="any_door_open",
    name="Any Door Open",
    state="{{ is_state('binary_sensor.front_door', 'on') }}",
    device_class="door",
)
template_select(
    id="house_scene",
    name="House Scene",
    state="{{ states('input_select.house_mode') }}",
    options="{{ ['home', 'away', 'night'] }}",
)
