"""Error case: `extra=` shadowing a declared builder keyword."""

from hassle import dashboard, raw_card, section, view


@dashboard(url_path="two-spellings", title="Two spellings")
def two_spellings():
    with view(title="V", extra={"title": "other"}), section():
        raw_card({"type": "markdown", "content": "hi"})
