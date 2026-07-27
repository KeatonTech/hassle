"""Golden case: `extra=` forward-compatibility passthrough on a visual card.

`extra=` merges verbatim into the card body alongside the typed keywords
(§5.3) -- this is the escape valve for an HA option `c.gauge` does not (yet)
model.
"""

from hassle import cards as c
from hassle import dashboard, view


@dashboard(url_path="cards-visual-extra", title="Visual extra=")
def cards_visual_extra():
    with view(title="Extra", type="masonry"):
        c.gauge(
            "sensor.cpu_temp",
            name="CPU Temp",
            extra={"card_mod": {"style": "ha-card { --gauge-color: red; }"}},
        )
