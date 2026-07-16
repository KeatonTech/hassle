"""Golden case: bare entity/area/floor/label target sugar --
`target=e.weather.home` compiles to `target={"entity_id": ...}`
identically; `area()`/`floor()`/`label()` target helper objects also accepted
directly as `target=`. Paired with `target_dict_parity/`'s explicit dict form
to prove compile parity.
"""

from hassle import area, automation, floor, label, service, state, when
from hassle.registry import entities as e


@automation(id="weather_update", alias="Weather update")
def weather_update():
    when(state("binary_sensor.trigger").to("on"))
    service("weather.get_forecasts", target=e.weather.home, type="daily")
    service("light.turn_on", target=area("office"))
    service("light.turn_off", target=floor("upstairs"))
    service("light.toggle", target=label("security"))
