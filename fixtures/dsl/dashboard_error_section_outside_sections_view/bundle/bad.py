"""Error case: `with section():` under a masonry view."""

from hassle import dashboard, raw_card, section, view


@dashboard(url_path="wrong-view", title="Wrong view")
def wrong_view():
    with view(title="V", type="masonry"), section():
        raw_card({"type": "markdown", "content": "hi"})
