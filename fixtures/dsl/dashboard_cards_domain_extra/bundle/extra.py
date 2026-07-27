"""Golden case: `extra=` forward-compatibility passthrough on a domain card.

`extra=` merges verbatim into the card body alongside the typed keywords
(§5.3) -- this is the escape valve for an HA option `c.light` does not (yet)
model.
"""

from hassle import cards as c
from hassle import dashboard, view


@dashboard(url_path="cards-domain-extra", title="Domain extra=")
def cards_domain_extra():
    with view(title="Extra", type="masonry"):
        c.light(
            "light.living_room",
            name="Living Room",
            extra={"card_mod": {"style": "ha-card { --paper-item-icon-color: red; }"}},
        )
