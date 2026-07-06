"""Error case: `template_number` declared without `set_value=` -- HA's
config-flow form schema requires a write-target action sequence for a
template NUMBER (docs/ha-api-notes.md §26.6). Omitting it must fail at
compile time, not silently pass validate and only fail on push."""

from hassle import template_number

template_number(
    name="Active HVAC Zones",
    state="{{ states.climate | selectattr('state', 'ne', 'off') | list | count }}",
    min=0,
    max=8,
    step=1,
)
