"""Golden case: repeat_until(cond) -> HA's `repeat.until` action."""

from hassle import automation, repeat_until, service, state, when


@automation(id="repeat_until_done", alias="Repeat until done")
def repeat_until_done():
    when(state("input_boolean.done").to("off"))
    with repeat_until(state("input_boolean.done").is_("on")):
        service("input_boolean.turn_on", target={"entity_id": "input_boolean.done"})
