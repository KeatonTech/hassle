"""Golden case: multiple triggers + a nested and/time/template condition block.

Mirrors fixtures/configs/automation_mixed_triggers_conditions.json.
"""

from hassle import (
    all_of,
    automation,
    only_if,
    service,
    state,
    template,
    time,
    when,
    with_trigger_options,
)


@automation(id="mixed_triggers_conditions", alias="Mixed Triggers and Conditions")
def mixed_triggers_conditions():
    when(
        with_trigger_options(state("binary_sensor.motion"), id="motion"),
        with_trigger_options(state("binary_sensor.door"), id="door"),
        time(at="06:00:00").with_options(id="morning"),
    )
    only_if(
        all_of(
            state("input_boolean.enable").is_("on"),
            time(weekday=["mon", "tue", "wed", "thu", "fri"]),
            template("{{ now().hour >= 6 and now().hour < 22 }}"),
        )
    )
    service("light.turn_on", target={"entity_id": "light.hallway"}, brightness=255)
