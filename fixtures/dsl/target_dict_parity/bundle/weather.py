"""Golden case: explicit `target={"entity_id": ...}` dict form (`ux/dsl-ergonomics`,
item 3) -- the pre-existing behavior, unchanged. Paired with `target_entity_sugar/`'s
bare entity/area/floor/label sugar to prove compile parity.
"""

from hassle import automation, service, state, when


@automation(id="weather_update", alias="Weather update")
def weather_update():
    when(state("binary_sensor.trigger").to("on"))
    service("weather.get_forecasts", target={"entity_id": "weather.home"}, type="daily")
    service("light.turn_on", target={"area_id": "office"})
    service("light.turn_off", target={"floor_id": "upstairs"})
    service("light.toggle", target={"label_id": "security"})
