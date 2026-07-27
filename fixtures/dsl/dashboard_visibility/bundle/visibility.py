"""Golden case: the `cond` vocabulary via `visibility=`.

Lovelace visibility conditions are a DIFFERENT schema from automation
conditions (`entity`/`state`/`state_not` keys, plus the UI-only `screen` and
`user` kinds), so they get their own small vocabulary
(docs/internals/dashboards-design.md §5.4). A verbatim dict is accepted
anywhere a condition is, so unknown future condition kinds round-trip raw.
"""

from hassle import dashboard, raw_card, section, view
from hassle.cards import cond

# Conditions are ordinary Python values, so they can be named and reused.
HOT_OUTSIDE = [
    cond.any(
        cond.numeric("sensor.outside_temp", above=25),
        cond.state("weather.home", not_="sunny"),
    ),
    cond.all(cond.not_(cond.state("light.hall", "off"))),
    {"condition": "future_kind", "kept": True},  # verbatim: an unmodelled kind
]


@dashboard(url_path="conditional-views", title="Conditional")
def conditional_views():
    with (
        view(title="Mobile", path="mobile", visibility=[cond.screen("(max-width: 600px)")]),
        section(visibility=cond.state("input_boolean.guest_mode", "on")),
    ):
        raw_card({"type": "markdown", "content": "Guest mode is on."})
    with (
        view(title="Admins", path="admins", visibility=[cond.user("abc123", "def456")]),
        section(visibility=HOT_OUTSIDE),
    ):
        raw_card({"type": "markdown", "content": "Hot outside."})
