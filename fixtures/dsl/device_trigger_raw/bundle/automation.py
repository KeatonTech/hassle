"""Golden case: `device` trigger builder (raw dict passthrough).

Mirrors fixtures/configs/automation_device_trigger.json.
"""

from hassle import automation, device, service, when


@automation(id="device_trigger_raw", alias="Device Trigger")
def device_trigger_raw():
    when(
        device(
            {
                "device_id": "1234567890abcdef",
                "domain": "zwave",
                "type": "scene_activation",
                "subtype": "scene_001",
            }
        )
    )
    service("scene.turn_on", target={"entity_id": "scene.evening"})
