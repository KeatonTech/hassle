"""The exact docs/internals/dashboards-design.md §0/§9.1 example dashboard --
used by `test_sim_dashboard_query.py`'s acceptance tests (the §9.1 examples
must work near-verbatim)."""

from hassle import cards as c
from hassle import dashboard, section, view
from hassle.cards import cond
from hassle.registry import entities as e

HEAT_PUMP_HEADS = [e.climate.living_room, e.climate.office, e.climate.bedroom]


@dashboard(url_path="climate-control", title="Climate", icon="mdi:thermostat")
def climate():
    with view(title="Overview", path="overview"):  # sections view
        with section():
            c.heading(heading="Heat pumps")
            for head in HEAT_PUMP_HEADS:  # compile-time Python
                c.thermostat(entity=head)
        with section(column_span=2):
            c.entities(*HEAT_PUMP_HEADS, title="All heads")
            with c.conditional(cond.state(e.input_boolean.guest_mode, "on")):
                c.markdown(content="Guest mode is on — hallway stays warm.")
