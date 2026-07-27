"""Error case: a card recorded directly under a `sections` view."""

from hassle import dashboard, raw_card, view


@dashboard(url_path="no-section", title="No section")
def no_section():
    with view(title="V"):
        raw_card({"type": "markdown", "content": "hi"})
