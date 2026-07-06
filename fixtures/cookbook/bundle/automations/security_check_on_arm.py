"""Cookbook recipe 13: security check on arm.

When the house is armed, run a check across doors/locks and notify if
anything is left open/unlocked -- `all_of` combining several state
conditions inside a single `only_if`.
"""

from hassle import all_of, automation, only_if, service, state, when


@automation(id="cookbook_security_check_on_arm", alias="Cookbook: security check on arm")
def cookbook_security_check_on_arm():
    when(state("input_boolean.armed").to("on"))
    only_if(
        all_of(
            state("binary_sensor.back_door").is_("off"),
            state("lock.front_door").is_("locked"),
        )
    )
    service("notify.mobile_app_keaton", message="Armed: all secure")
