"""Golden case: `c.entity` -- `attribute=`, plus an action passthrough."""

from hassle import cards as c
from hassle import dashboard, section, view
from hassle.registry import entities as e


@dashboard(url_path="display-entity", title="Entity")
def display_entity():
    with view(title="Overview"), section():
        c.entity(
            e.sensor.outside_temp,
            attribute="battery_level",
            name="Battery",
            icon="mdi:battery",
            hold_action={"action": "more-info"},
        )
