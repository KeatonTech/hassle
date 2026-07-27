"""Golden case: `c.button` -- `tap_action=` (the modern `perform-action` spelling)."""

from hassle import cards as c
from hassle import dashboard, section, view
from hassle.registry import entities as e


@dashboard(url_path="display-button", title="Button")
def display_button():
    with view(title="Overview"), section():
        c.button(
            entity=e.script.movie_time,
            name="Movie time",
            icon="mdi:movie",
            tap_action={"action": "perform-action", "perform_action": "script.movie_time"},
        )
