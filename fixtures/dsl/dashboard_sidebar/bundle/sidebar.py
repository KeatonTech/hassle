"""Golden case: a `sidebar` view.

The fourth literal `type=` spelling (§5.2). Like masonry and panel it holds
cards directly rather than sections -- HA renders them in a main column plus a
narrow sidebar column.
"""

from hassle import dashboard, raw_card, view


@dashboard(url_path="sidebar-layout", title="Sidebar", icon="mdi:dock-left")
def sidebar_layout():
    with view(title="Split", path="split", type="sidebar"):
        raw_card({"type": "markdown", "content": "main column"})
        raw_card({"type": "markdown", "content": "sidebar column"})
