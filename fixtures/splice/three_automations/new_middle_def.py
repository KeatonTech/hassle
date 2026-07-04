# hassle: updated from UI on 2026-07-03
@automation(id="middle_automation", alias="Middle: edited in the UI")
def middle_automation():
    when(state(e.binary_sensor.hall_motion).to("off"))
    service("light.turn_off", target={"entity_id": "light.hallway"})
    service("light.turn_off", target={"entity_id": "light.landing"})
