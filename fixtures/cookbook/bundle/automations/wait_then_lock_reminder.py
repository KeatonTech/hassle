"""Cookbook recipe 19: wait for the door to close, then remind to lock it.

`wait_for` blocks the action sequence until the door closes (or times out);
`continue_on_timeout` lets the reminder still fire either way.
"""

from hassle import automation, service, state, wait_for, when


@automation(id="cookbook_wait_then_lock_reminder", alias="Cookbook: wait then lock reminder")
def cookbook_wait_then_lock_reminder():
    when(state("binary_sensor.front_door").to("open"))
    wait_for(
        state("binary_sensor.front_door").to("closed"),
        timeout="00:05:00",
        continue_on_timeout=True,
    )
    service("notify.mobile_app_keaton", message="Don't forget to lock the front door")
