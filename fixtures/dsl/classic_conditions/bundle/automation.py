"""Golden case: every classic condition builder in one automation.

Exercises state/numeric_state/sun/time/zone/template conditions plus the
`condition: trigger` block referencing a trigger id= (DESIGN §5.4). Field
shapes mirror fixtures/configs/automation_condition_*.json.
"""

from hassle import (
    automation,
    numeric_state,
    only_if,
    service,
    state,
    sun,
    template,
    time,
    trigger_condition,
    when,
    zone,
)


@automation(id="classic_conditions", alias="Classic Conditions")
def classic_conditions():
    when(numeric_state("sensor.humidity", above=0).with_options(id="motion"))
    only_if(
        state("input_boolean.enable_automation").is_("on"),
        numeric_state("sensor.humidity", above=60),
        sun(after="sunset", after_offset="-01:00:00"),
        time(after="22:00:00", before="06:00:00", weekday=["mon", "tue", "wed", "thu", "fri"]),
        zone("device_tracker.john", zone="zone.work"),
        template("{{ now().hour >= 6 and now().hour < 22 }}"),
        trigger_condition("motion"),
    )
    service("light.turn_on", target={"entity_id": "light.hallway"})
