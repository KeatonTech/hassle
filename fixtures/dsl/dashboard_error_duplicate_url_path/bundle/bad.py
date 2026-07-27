"""Error case: two dashboards claiming the same `url_path`.

Identity rides the normal registry path: the object key is
`dashboard:<url_path>`, so this collides exactly like two automations claiming
one `id=` -- but the fix names the DASHBOARD identity rule, since a dashboard
has no `id=` kwarg and its function name is not its identity.
"""

from hassle import dashboard, raw_card, section, view


@dashboard(url_path="twice-claimed", title="First")
def first():
    with view(title="V"), section():
        raw_card({"type": "markdown", "content": "one"})


@dashboard(url_path="twice-claimed", title="Second")
def second():
    with view(title="V"), section():
        raw_card({"type": "markdown", "content": "two"})
