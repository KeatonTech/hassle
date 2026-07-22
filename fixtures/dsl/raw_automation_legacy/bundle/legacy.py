"""Golden case: raw_automation authored with legacy singular keys.

Proves normalize_ha runs on the raw body: the bundle writes the pre-2024.10
singular schema (trigger/condition/action + service:), and the compiler stores
the canonical plural form (triggers/conditions/actions + action:), exactly as
HA normalizes on storage (docs/internals/ha-api-notes.md §10.1).
"""

from hassle import raw_automation


@raw_automation(id="legacy_device_automation")
def legacy_device_automation():
    return {
        "alias": "Legacy Device Automation",
        "trigger": [{"platform": "state", "entity_id": "binary_sensor.motion", "to": "on"}],
        "condition": [
            {"condition": "state", "entity_id": "input_boolean.guest_mode", "state": "on"}
        ],
        "action": [
            {"service": "light.turn_on", "target": {"entity_id": "light.hallway"}},
        ],
        "mode": "single",
    }
