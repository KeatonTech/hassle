"""Golden case: purpose-specific trigger, floor target, behavior=each (M1 test 10).

Mirrors fixtures/configs/automation_purpose_trigger_floor_device.json (first
trigger only; the device-target trigger is covered by purpose_trigger_device).
"""

from hassle import automation, floor, on, service, when


@automation(id="purpose_trigger_floor_each", alias="Purpose Trigger Floor Behavior Each")
def purpose_trigger_floor_each():
    when(on("battery.became_low", target=floor("upstairs"), behavior="each"))
    service("notify.mobile_app_keaton", message="Device event detected")
