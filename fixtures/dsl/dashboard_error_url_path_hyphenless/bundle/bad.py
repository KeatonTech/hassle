"""Error case: a `url_path=` with no hyphen (HA requires one)."""

from hassle import dashboard, raw_card, section, view


@dashboard(url_path="climate", title="Climate")
def climate():
    with view(title="V"), section():
        raw_card({"type": "markdown", "content": "hi"})
