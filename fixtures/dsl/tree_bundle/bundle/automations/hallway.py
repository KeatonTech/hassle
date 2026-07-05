"""Golden case (M7.1): DESIGN §6-shaped tree bundle. This mirrors DESIGN §5.3's
worked example verbatim -- imports a helper from `helpers/` and a macro from
`lib/`, both one subdirectory below the bundle root."""

from helpers.modes import guest_mode
from lib.notify import notify_adults

from hassle import automation, delay, only_if, service, state, sun, when
from hassle.registry import entities as e


@automation(
    id="hall_light_on_motion",
    alias="Hallway: light on motion",
    mode="restart",
)
def hall_light_on_motion():
    when(state(e.binary_sensor.hall_motion).to("on"))
    only_if(
        state(guest_mode).is_("off"),
        sun(after="sunset", after_offset="-00:30"),
    )
    service("light.turn_on", entity_id=e.light.hallway, brightness_pct=60, transition=2)
    delay(minutes=5)
    service("light.turn_off", entity_id=e.light.hallway)


@automation(id="front_door_notify", alias="Front door opened")
def front_door_notify():
    when(state(e.binary_sensor.front_door).to("open"))
    notify_adults("Front door opened")
