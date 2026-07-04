"""Golden case: `any_of`/`all_of`/`not_` condition combinators.

Mirrors fixtures/configs/automation_condition_and_or_not.json (and/or/not
condition blocks).
"""

from hassle import all_of, any_of, automation, not_, only_if, service, state, when


@automation(id="condition_combinators", alias="Condition And Or Not")
def condition_combinators():
    when(state("binary_sensor.motion").to("on"))
    only_if(
        all_of(
            state("input_boolean.mode").is_("on"),
            any_of(
                state("light.bedroom").is_("on"),
                state("light.living_room").is_("on"),
            ),
            not_(state("input_boolean.away").is_("on")),
        )
    )
    service("light.turn_on", target={"entity_id": "light.hallway"})
