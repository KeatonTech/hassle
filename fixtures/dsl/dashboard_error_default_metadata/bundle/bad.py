"""Error case: `@dashboard(default=True)` also sets registry metadata.

THE default dashboard has no entry in HA's dashboard registry, so there is
nowhere to store a title/icon/sidebar/admin flag.
"""

from hassle import dashboard, raw_card, section, view


@dashboard(default=True, title="Home", icon="mdi:home")
def home():
    with view(title="V"), section():
        raw_card({"type": "markdown", "content": "hi"})
