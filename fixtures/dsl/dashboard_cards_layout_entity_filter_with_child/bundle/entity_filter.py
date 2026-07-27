"""Golden case: `c.entity_filter` WITH its presentation card."""

from hassle import cards as c
from hassle import dashboard, raw_card, section, view
from hassle.registry import entities as e


@dashboard(url_path="layout-entity-filter-with-child", title="Entity filter (with card)")
def layout_entity_filter_with_child():
    with (
        view(title="Overview"),
        section(),
        c.entity_filter(entities=[e.light.kitchen, e.light.living_room], state_filter=["on"]),
    ):
        raw_card({"type": "glance"})
