"""Golden case: a `panel` view -- exactly one full-width card.

More (or fewer) than one card in a panel view is a compile-time
`PanelViewArityError` (docs/internals/dashboards-design.md §5.2/§5.6).
"""

from hassle import dashboard, raw_card, view


@dashboard(url_path="big-map", title="Map", icon="mdi:map")
def big_map():
    with view(title="Map", path="map", type="panel"):
        raw_card({"type": "map", "entities": ["device_tracker.phone"]})
