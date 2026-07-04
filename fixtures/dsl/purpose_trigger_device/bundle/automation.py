"""Golden case: purpose-specific trigger, device_id target (M1 test 10).

Mirrors the second trigger of
fixtures/configs/automation_purpose_trigger_floor_device.json.
"""

from hassle import automation, device_id, on, service, when


@automation(id="purpose_trigger_device", alias="Purpose Trigger Device Target")
def purpose_trigger_device():
    when(on("vacuum.returned_to_dock", target=device_id("aaaabbbbccccdddd1111222233334444")))
    service("notify.mobile_app_keaton", message="Device event detected")
