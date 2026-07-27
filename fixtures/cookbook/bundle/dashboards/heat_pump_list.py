"""Cookbook recipe: a dashboard from a Python list.

The headline dashboards pattern (docs/internals/dashboards-design.md §0):
Python is the metaprogramming layer, so a card per heat-pump head is a
compile-time `for` loop over a plain list, not copy-paste. The `c.entities`
card built from the SAME list stays in sync automatically -- add a head to
`HEAT_PUMP_HEADS` and both the loop and the entities card pick it up the next
time this compiles, with nothing else to edit.
"""

from hassle import cards as c
from hassle import dashboard, section, view

HEAT_PUMP_HEADS = [
    "climate.living_room",
    "climate.bedroom_thermostat",
    "climate.office_thermostat",
]


@dashboard(url_path="cookbook-heat-pumps", title="Heat Pumps", icon="mdi:heat-pump")
def cookbook_heat_pumps():
    with view(title="Overview", path="overview"):
        with section():
            c.heading(heading="Heat pumps")
            for head in HEAT_PUMP_HEADS:
                c.thermostat(entity=head)
        with section(column_span=2):
            c.entities(*HEAT_PUMP_HEADS, title="All heads")
