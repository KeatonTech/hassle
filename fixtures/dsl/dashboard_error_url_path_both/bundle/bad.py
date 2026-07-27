"""Error case: `@dashboard()` sets BOTH `url_path=` and `default=True`."""

from hassle import dashboard, raw_card, section, view


@dashboard(url_path="both-ways", default=True)
def both_ways():
    with view(title="V"), section():
        raw_card({"type": "markdown", "content": "hi"})
