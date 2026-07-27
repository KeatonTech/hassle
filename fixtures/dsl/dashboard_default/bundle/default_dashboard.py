"""Golden case: THE default dashboard.

`default=True` declares the dashboard HA serves at `/lovelace`. It has no
registry item, so the envelope's `meta` is explicitly `null` and the object key
uses the `default` identity sentinel -- collision-free because a real
`url_path` must contain a hyphen (docs/internals/dashboards-design.md §3.1/§3.2).
"""

from hassle import dashboard, raw_card, section, view


@dashboard(default=True)
def home():
    with view(title="Home", path="home"), section(column_span=2):
        raw_card({"type": "markdown", "content": "The default dashboard."})
