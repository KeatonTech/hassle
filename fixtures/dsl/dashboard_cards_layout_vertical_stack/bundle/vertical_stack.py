"""Golden case: `c.vertical_stack` -- title, `extra=` round-trip, two children.

docs/internals/dashboards-design.md §5.3: every builder takes `extra=`
verbatim passthrough; `unknown_option` here is not a typed `vertical_stack`
kwarg, so it must survive the compile untouched.
"""

from hassle import cards as c
from hassle import dashboard, raw_card, section, view

CARD_A = {"type": "markdown", "content": "one"}
CARD_B = {"type": "markdown", "content": "two"}


@dashboard(url_path="layout-vertical-stack", title="Vertical stack")
def layout_vertical_stack():
    with (
        view(title="Overview"),
        section(),
        c.vertical_stack(title="Two cards", extra={"unknown_option": 7}),
    ):
        raw_card(CARD_A)
        raw_card(CARD_B)
