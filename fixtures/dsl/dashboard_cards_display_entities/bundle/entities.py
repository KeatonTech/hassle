"""Golden case: `c.entities` -- mixed varargs rows (`EntityRef`, `str`, a `dict` divider row)."""

from hassle import cards as c
from hassle import dashboard, section, view
from hassle.registry import entities as e


@dashboard(url_path="display-entities", title="Entities")
def display_entities():
    with view(title="Overview"), section():
        c.entities(
            e.light.kitchen,
            "light.living_room",
            {"type": "divider"},
            {"entity": "climate.office", "tap_action": {"action": "more-info"}},
            title="All lights",
            state_color=True,
        )
