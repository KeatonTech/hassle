"""Cookbook recipe 4: actionable mobile notification (task #30).

Sends an actionable notification with two buttons ("Open Blinds"/"Close
Blinds") and opens/closes the upstairs blinds depending on which one the
user taps -- built entirely on the `notify_mobile`/`action` recipe helpers
(`lib/notify_actions.py`), which are themselves built on the public
`capture_actions`/`emit_actions` seam (task #30, `hassle.compiler.recording`).
"""

from lib.notify_actions import action, notify_mobile

from hassle import automation, state, when
from hassle.services import cover


@automation(id="cookbook_notify_with_actions", alias="Cookbook: door unlocked notify")
def cookbook_notify_with_actions():
    when(state("lock.front_door").to("unlocked"))
    with notify_mobile(title="Front Door Unlocked", message="Adjust the upstairs blinds?"):
        with action("Open Blinds", icon="mdi:blinds-open"):
            cover.open_cover(target={"entity_id": ["cover.bedroom_blinds", "cover.office_blinds"]})
        with action("Close Blinds"):
            cover.close_cover(target={"entity_id": ["cover.bedroom_blinds", "cover.office_blinds"]})
