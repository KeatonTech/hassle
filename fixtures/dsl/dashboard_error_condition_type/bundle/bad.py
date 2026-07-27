"""Error case: an AUTOMATION condition builder in a dashboard `visibility=` slot."""

from hassle import dashboard, raw_card, section, state, view


@dashboard(url_path="wrong-condition", title="Wrong condition")
def wrong_condition():
    with view(title="V", visibility=[state("light.hall").is_("on")]), section():
        raw_card({"type": "markdown", "content": "hi"})
