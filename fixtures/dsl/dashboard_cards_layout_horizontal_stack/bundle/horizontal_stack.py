"""Golden case: `c.horizontal_stack` -- no `title` option (unlike `vertical_stack`)."""

from hassle import cards as c
from hassle import dashboard, raw_card, section, view


@dashboard(url_path="layout-horizontal-stack", title="Horizontal stack")
def layout_horizontal_stack():
    with view(title="Overview"), section(), c.horizontal_stack():
        raw_card({"type": "markdown", "content": "left"})
        raw_card({"type": "markdown", "content": "right"})
