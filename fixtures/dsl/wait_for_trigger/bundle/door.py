"""Golden case: wait_for(trigger, timeout=, continue_on_timeout=) -> `wait_for_trigger`."""

from hassle import automation, service, state, wait_for, when


@automation(id="wait_for_door", alias="Wait for trigger")
def wait_for_door():
    when(state("button.start").to("on"))
    wait_for(
        state("binary_sensor.door").to("off"),
        timeout="00:10:00",
        continue_on_timeout=True,
    )
    service("notify.mobile_app", message="Wait completed")
