"""Golden case: `c.entity_filter` WITHOUT a presentation card (zero children).

HA falls back to a bare entity list when the `card:` key is entirely absent,
which is exactly what an empty block produces.
"""

from hassle import cards as c
from hassle import dashboard, section, view
from hassle.registry import entities as e


@dashboard(url_path="layout-entity-filter-no-child", title="Entity filter (no card)")
def layout_entity_filter_without_child():
    with (
        view(title="Overview"),
        section(),
        c.entity_filter(entities=[e.light.kitchen, "light.hallway"], show_empty=False),
    ):
        pass
