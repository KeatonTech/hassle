"""Golden case: `c.conditional` -- exactly one child card behind its conditions."""

from hassle import cards as c
from hassle import dashboard, raw_card, section, view
from hassle.cards import cond


@dashboard(url_path="layout-conditional", title="Conditional")
def layout_conditional():
    with (
        view(title="Overview"),
        section(),
        c.conditional(cond.state("input_boolean.guest_mode", "on")),
    ):
        raw_card({"type": "markdown", "content": "Guest mode is on."})
