"""Golden case: the `extra=` forward-compat valve on a leaf display card.

`grid_options` is not a typed `c.button` kwarg -- a hypothetical HA option
Hassle does not model yet -- and must survive the compile verbatim, merged
alongside the typed options rather than collapsing the whole card to
`raw_card` (§5.3).
"""

from hassle import cards as c
from hassle import dashboard, section, view


@dashboard(url_path="display-extra-roundtrip", title="Extra roundtrip")
def display_extra_roundtrip():
    with view(title="Overview"), section():
        c.button(
            entity="light.kitchen",
            name="Kitchen",
            extra={"grid_options": {"columns": 6, "rows": 1}},
        )
