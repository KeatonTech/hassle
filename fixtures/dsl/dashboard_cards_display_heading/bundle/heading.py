"""Golden case: `c.heading` -- `heading_style=`, `badges=` (bare entity + verbatim dict)."""

from hassle import cards as c
from hassle import dashboard, section, view
from hassle.registry import entities as e


@dashboard(url_path="display-heading", title="Heading")
def display_heading():
    with view(title="Overview"), section():
        c.heading(
            heading="Living room",
            heading_style="title",
            icon="mdi:sofa",
            badges=[e.sensor.outside_temp, {"type": "state-label", "entity": "light.hall"}],
        )
