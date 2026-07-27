"""Golden case: masonry views, both storage spellings.

`type=None` emits NO `type` key at all -- the legacy-masonry shape the HA UI
still stores for older dashboards; `type="masonry"` emits the literal value.
One builder covers both, so the decompiler can emit exactly what is stored
(docs/internals/dashboards-design.md §5.2, §2.2 item 4).
"""

from hassle import dashboard, raw_card, view


@dashboard(url_path="legacy-masonry", title="Legacy", icon="mdi:view-dashboard")
def legacy_masonry():
    with view(title="Cards", path="cards", type=None):
        raw_card({"type": "markdown", "content": "one"})
        raw_card({"type": "markdown", "content": "two"})
    with view(title="Modern", path="modern", type="masonry"):
        raw_card({"type": "markdown", "content": "three"})
