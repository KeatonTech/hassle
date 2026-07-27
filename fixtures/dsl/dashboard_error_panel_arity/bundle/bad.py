"""Error case: a `panel` view with more than one card."""

from hassle import dashboard, raw_card, view


@dashboard(url_path="two-panels", title="Two panels")
def two_panels():
    with view(title="V", type="panel"):
        raw_card({"type": "markdown", "content": "one"})
        raw_card({"type": "markdown", "content": "two"})
