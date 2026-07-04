"""Golden case: parallel() -> HA's `parallel` action.

Matches fixtures/configs/automation_parallel_action.json's shape: each
top-level action recorded in the body becomes its own one-action `sequence`
branch.
"""

from hassle import automation, parallel, service, state, when


@automation(id="guest_parallel", alias="Guest parallel")
def guest_parallel():
    when(state("binary_sensor.guest_arrived").to("on"))
    with parallel():
        service("light.turn_on", target={"entity_id": "light.hallway"})
        service("light.turn_on", target={"entity_id": "light.living_room"})
        service("script.greet_guest")
