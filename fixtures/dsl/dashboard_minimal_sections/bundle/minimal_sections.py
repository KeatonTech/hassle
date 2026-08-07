"""Golden case: the smallest useful dashboard -- one sections view, one section.

`type=` defaults to `"sections"` and is materialized EXPLICITLY into the stored
config (docs/internals/dashboards-design.md §5.2).
"""

from hassle import dashboard, raw_card, section, view


@dashboard(
    url_path="home-main",
    title="Home",
    icon="mdi:home",
    show_in_sidebar=True,
    require_admin=False,
)
def home_main():
    with view(title="Overview", path="overview"), section():
        raw_card({"type": "markdown", "content": "Welcome home."})
