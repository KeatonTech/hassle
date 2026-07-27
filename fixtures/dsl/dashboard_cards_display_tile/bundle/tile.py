"""Golden case: `c.tile` -- `features=`, plus both `tap_action` forms (§5.3).

`tap_action=` is a typed kwarg that widens to a verbatim `dict` ("dict
passthrough"); `icon_tap_action` is a real tile-card option Hassle leaves
undeclared on purpose, so it reaches the stored card only through `extra=`
("extra passthrough") -- both mechanisms exercised on the same card.
"""

from hassle import cards as c
from hassle import dashboard, section, view
from hassle.registry import entities as e


@dashboard(url_path="display-tile", title="Tile")
def display_tile():
    with view(title="Overview"), section():
        c.tile(
            e.climate.living_room,
            color="blue",
            vertical=True,
            features=[{"type": "climate-hvac-modes"}],
            tap_action={"action": "more-info"},
            extra={"icon_tap_action": {"action": "toggle"}},
        )
