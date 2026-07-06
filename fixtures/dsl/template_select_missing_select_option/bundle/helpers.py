"""Error case: `template_select` declared without `select_option=` -- HA's
config-flow form schema requires a write-target action sequence for a
template SELECT (docs/ha-api-notes.md §26.6). Omitting it must fail at
compile time, not silently pass validate and only fail on push."""

from hassle import template_select

template_select(
    name="House Scene",
    state="{{ states('input_select.house_mode') }}",
    options="{{ ['home', 'away', 'night'] }}",
)
