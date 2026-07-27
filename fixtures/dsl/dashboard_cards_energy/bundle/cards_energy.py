"""Golden case: DB3c's Energy dashboard card family (§2.3, §5.3, §6.1.1).

One usage of every `hassle.cards` builder in `cards/energy.py` -- all 12
built-in Energy cards. Ten of them are plain `{type, collection_key?}` shapes;
`energy_distribution` also takes `link_dashboard=`, and `energy_sankey` also
takes `title=` (see that module's docstring for the DB0 note on the latter).
"""

from hassle import cards as c
from hassle import dashboard, view


@dashboard(url_path="cards-energy", title="Energy")
def cards_energy():
    with view(title="Energy", type="masonry"):
        c.energy_date_selection(collection_key="energy_secondary")
        c.energy_usage_graph(collection_key="energy_secondary")
        c.energy_solar_graph(collection_key="energy_secondary")
        c.energy_gas_graph(collection_key="energy_secondary")
        c.energy_water_graph(collection_key="energy_secondary")
        c.energy_distribution(collection_key="energy_secondary", link_dashboard=True)
        c.energy_sources_table(collection_key="energy_secondary")
        c.energy_grid_neutrality_gauge(collection_key="energy_secondary")
        c.energy_solar_consumed_gauge(collection_key="energy_secondary")
        c.energy_carbon_consumed_gauge(collection_key="energy_secondary")
        c.energy_self_sufficiency_gauge(collection_key="energy_secondary")
        c.energy_sankey(collection_key="energy_secondary", title="Flows")
