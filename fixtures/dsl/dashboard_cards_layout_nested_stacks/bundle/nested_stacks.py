"""Golden case: containers nest three deep -- vertical -> horizontal -> grid.

Also the `c.grid(columns=, square=)` golden usage: NOT the same construct as
`section()` even though both store `{"type": "grid", ...}` -- position
disambiguates (§6.1.1).
"""

from hassle import cards as c
from hassle import dashboard, raw_card, section, view


@dashboard(url_path="layout-nested-stacks", title="Nested stacks")
def layout_nested_stacks():
    with (
        view(title="Overview"),
        section(),
        c.vertical_stack(),
        c.horizontal_stack(),
        c.grid(columns=2, square=True),
    ):
        raw_card({"type": "markdown", "content": "deepest"})
