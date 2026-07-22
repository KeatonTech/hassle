"""Cookbook recipe 14: timer-based reminder.

Starting the kitchen timer when the oven turns on, and notifying when it
finishes (a `timer.*` entity moves to `idle` when it completes or is
cancelled -- gated here on `armed` so a manual cancel doesn't also notify).
"""

from hassle import automation, only_if, service, state, when


@automation(id="cookbook_start_kitchen_timer", alias="Cookbook: start kitchen timer")
def cookbook_start_kitchen_timer():
    when(state("switch.washing_machine").to("on"))
    service("timer.start", target={"entity_id": "timer.kitchen"}, duration="00:45:00")


@automation(id="cookbook_kitchen_timer_done", alias="Cookbook: kitchen timer done")
def cookbook_kitchen_timer_done():
    when(state("timer.kitchen").to("idle"))
    only_if(state("input_boolean.armed").is_("on"))
    service("notify.mobile_app_kai", message="Kitchen timer finished")
