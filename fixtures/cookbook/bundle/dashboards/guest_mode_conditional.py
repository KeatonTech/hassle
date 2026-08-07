"""Cookbook recipe: conditional guest-mode section.

Lovelace visibility/conditional conditions (`hassle.cards.cond`) are a
DIFFERENT vocabulary from automation conditions (docs/internals/
dashboards-design.md §5.4 -- `entity`/`state`/`state_not` keys, not
`entity_id`/`condition`). `c.conditional(...)` wraps exactly one child card,
shown only when every condition passes; here it hides a guest-mode banner
behind `cond.state(...)` the same way the design doc's own §0 example does.
"""

from hassle import cards as c
from hassle import dashboard, section, view
from hassle.cards import cond


@dashboard(url_path="cookbook-guest-mode", title="Guest Mode")
def cookbook_guest_mode():
    with view(title="Overview", path="overview"), section():
        c.heading(heading="Welcome")
        with c.conditional(cond.state("input_boolean.guest_mode", "on")):
            c.markdown(content="Guest mode is on -- make yourself at home!")
