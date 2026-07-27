"""Golden case: `extra=` forward-compatibility passthrough on a media card."""

from hassle import cards as c
from hassle import dashboard, view


@dashboard(url_path="cards-media-extra", title="Media extra=")
def cards_media_extra():
    with view(title="Extra", type="masonry"):
        c.iframe(
            "https://example.com/panel",
            extra={"loading": "lazy", "sandbox": "allow-scripts"},
        )
