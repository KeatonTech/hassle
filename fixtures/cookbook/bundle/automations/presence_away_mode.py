"""Cookbook recipe 2: presence-based away mode.

Either phone leaving re-checks presence; `all_of` gates the action on BOTH
being away before arming, so a single phone leaving (while the other is
still home) does nothing.
"""

from hassle import all_of, automation, only_if, service, state, when


@automation(id="cookbook_presence_away", alias="Cookbook: everyone left")
def cookbook_presence_away():
    when(state("device_tracker.keaton_phone").to("not_home"))
    when(state("device_tracker.john_phone").to("not_home"))
    only_if(
        all_of(
            state("device_tracker.keaton_phone").is_("not_home"),
            state("device_tracker.john_phone").is_("not_home"),
        )
    )
    service("input_boolean.turn_on", target={"entity_id": "input_boolean.armed"})
