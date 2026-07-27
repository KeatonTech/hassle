"""Error case: `@dashboard()` declares neither `url_path=` nor `default=True`."""

from hassle import dashboard, raw_card, section, view


@dashboard(title="Nameless")
def nameless():
    with view(title="V"), section():
        raw_card({"type": "markdown", "content": "hi"})
