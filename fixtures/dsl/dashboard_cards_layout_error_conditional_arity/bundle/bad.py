"""Error case: `c.conditional` recorded with two cards instead of exactly one."""

from hassle import cards as c
from hassle import dashboard, raw_card, section, view
from hassle.cards import cond


@dashboard(url_path="conditional-arity-bad", title="Bad conditional")
def conditional_arity_bad():
    with view(title="V"), section(), c.conditional(cond.state("light.hall", "on")):
        raw_card({"type": "markdown", "content": "one"})
        raw_card({"type": "markdown", "content": "two"})
