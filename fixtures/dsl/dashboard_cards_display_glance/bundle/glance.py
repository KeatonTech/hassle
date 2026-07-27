"""Golden case: `c.glance` -- the same rows convention as `c.entities`."""

from hassle import cards as c
from hassle import dashboard, section, view
from hassle.registry import entities as e


@dashboard(url_path="display-glance", title="Glance")
def display_glance():
    with view(title="Overview"), section():
        c.glance(
            e.sensor.outside_temp,
            e.sensor.outside_humidity,
            title="Outside",
            columns=2,
            show_name=False,
        )
