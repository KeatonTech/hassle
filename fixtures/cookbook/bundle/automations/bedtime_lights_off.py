"""Cookbook recipe 12: lights off at bedtime.

A single time trigger turns off every downstairs light in one action; a
`choose` decides whether to also arm the alarm depending on guest mode.
"""

from hassle import automation, choose, service, state, time, when


@automation(id="cookbook_bedtime_lights_off", alias="Cookbook: bedtime lights off")
def cookbook_bedtime_lights_off():
    when(time(at="23:00:00"))
    service("light.turn_off", entity_id=["light.living_room", "light.kitchen", "light.hallway"])
    with choose() as c:
        with c.when_(state("input_boolean.guest_mode").is_("off")):
            service(
                "alarm_control_panel.alarm_arm_home",
                target={"entity_id": "alarm_control_panel.home"},
            )
        with c.default():
            service(
                "notify.mobile_app_kai", message="Bedtime lights off (guest mode: alarm skipped)"
            )
