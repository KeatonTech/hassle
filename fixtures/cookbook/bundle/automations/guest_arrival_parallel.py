"""Cookbook recipe 21: guest arrival, several things at once.

`parallel()` runs a notify and two light calls concurrently instead of one
after another (DESIGN §5.5) -- useful when order truly doesn't matter and
you don't want one slow step to delay the rest.
"""

from hassle import automation, parallel, service, state, when


@automation(id="cookbook_guest_arrival_parallel", alias="Cookbook: guest arrival (parallel)")
def cookbook_guest_arrival_parallel():
    when(state("input_boolean.guest_mode").to("on"))
    with parallel():
        service("light.turn_on", target={"entity_id": "light.living_room"})
        service("light.turn_on", target={"entity_id": "light.hallway"})
        service("notify.mobile_app_keaton", message="Guest mode enabled")
