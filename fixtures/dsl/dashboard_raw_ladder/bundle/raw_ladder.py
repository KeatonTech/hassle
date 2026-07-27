"""Golden case: the structural raw ladder (I3).

Granular escape hatches at every level, mirroring `raw_trigger`/`raw_action`:
an unknown CARD stays a `raw_card` inside a modelled section; a section whose
own keys are unmodelled is a whole `raw_section`; a view Hassle does not model
at all (a strategy view) is a whole `raw_view`. Never raw a parent merely
because a child rawed (docs/internals/dashboards-design.md §5.5).
"""

from hassle import dashboard, raw_card, raw_section, raw_view, section, view


@dashboard(url_path="raw-ladder", title="Raw ladder")
def raw_ladder():
    # Level 1: a third-party card, inside a fully modelled view + section.
    with view(title="Cards", path="cards"), section():
        raw_card({"type": "custom:bubble-card", "card_type": "button"})
    # Level 2: a section whose own keys are unmodelled.
    with view(title="Sections", path="sections"):
        raw_section(
            {
                "type": "grid",
                "column_span": 2,
                "invented_section_key": ["kept"],
                "cards": [{"type": "markdown", "content": "raw section"}],
            }
        )
    # Level 3: a whole view Hassle does not model (a strategy view).
    raw_view({"strategy": {"type": "original-states"}, "title": "Auto"})
