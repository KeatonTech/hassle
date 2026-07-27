"""Golden case: a Python `for` generating cards at COMPILE time.

The headline dashboards feature (docs/internals/dashboards-design.md §0/D-G2):
Python is the metaprogramming layer, so a card per heat-pump head is a loop
over a list, not copy-paste. The compiled config below is fully expanded --
nothing about the loop survives into what HA stores.
"""

from hassle import dashboard, raw_card, section, view

HEAT_PUMP_HEADS = ["climate.living_room", "climate.office", "climate.bedroom"]


@dashboard(url_path="heat-pumps", title="Heat pumps", icon="mdi:heat-pump")
def heat_pumps():
    with view(title="Overview", path="overview"), section(column_span=2):
        raw_card({"type": "heading", "heading": "Heat pumps"})
        for head in HEAT_PUMP_HEADS:
            raw_card({"type": "thermostat", "entity": head})
