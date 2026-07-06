"""Cookbook recipe 20: purpose-trigger motion with an area target (2026.7+).

`on("motion.detected", target=area(...))` -- the modern UI-default shape
(DESIGN §5.4) instead of a classic `state()` trigger on a specific sensor.
"""

from hassle import area, automation, minutes, on, service, when


@automation(id="cookbook_purpose_trigger_office_motion", alias="Cookbook: office motion (area)")
def cookbook_purpose_trigger_office_motion():
    when(on("motion.detected", target=area("office"), behavior="first", for_=minutes(1)))
    service("light.turn_on", target={"entity_id": "light.office_ceiling"})
