"""Cookbook recipe 6: guest mode suppresses an automation.

`only_if` gating on an `input_boolean` helper -- the most common "quiet
hours"/"do not disturb" shape.
"""

from hassle import automation, only_if, service, state, when


@automation(id="cookbook_guest_mode_gate", alias="Cookbook: guest mode gate")
def cookbook_guest_mode_gate():
    when(state("binary_sensor.back_door").to("open"))
    only_if(state("input_boolean.guest_mode").is_("off"))
    service("notify.mobile_app_keaton", message="Back door opened")
