"""Golden case: kitchen-sink-lite — every M1-core primitive in one automation.

Exercises: full @automation option set (id/alias/mode/max/description), multiple
triggers in one when(), from+to on a state trigger, multiple conditions in one
only_if(), delay with seconds, and a service call with an explicit target= and
data kwargs.
"""

from hassle import automation, delay, only_if, service, state, when


@automation(
    id="sink",
    alias="Kitchen sink lite",
    description="every core primitive",
    mode="queued",
    max=10,
)
def sink():
    when(
        state("binary_sensor.door").to("open"),
        state("binary_sensor.window").is_("on").to("off"),
    )
    only_if(
        state("input_boolean.armed").is_("on"),
        state("alarm_control_panel.home").is_("armed_away"),
    )
    service(
        "notify.mobile_app",
        target={"entity_id": "notify.phone"},
        message="Door opened",
    )
    delay(seconds=30)
    service("light.turn_off", entity_id="light.hallway")
