"""Cookbook recipe 24: stop the automation early if a condition isn't met.

`stop(message, ...)` inside an `if_then` block ends the run right there
(distinct from `only_if`, which would skip the WHOLE automation before any
action ran) -- useful when you want the first action or two to always run,
then bail before the rest.
"""

from hassle import automation, if_then, service, state, stop, when


@automation(id="cookbook_stop_if_armed", alias="Cookbook: stop if armed")
def cookbook_stop_if_armed():
    when(state("binary_sensor.workshop_door").to("open"))
    service("light.turn_on", target={"entity_id": "light.workshop"})
    with if_then(state("input_boolean.armed").is_("on")):
        stop("Workshop is armed -- skipping the rest of the sequence")
    service("notify.mobile_app_kai", message="Workshop door opened (unarmed)")
