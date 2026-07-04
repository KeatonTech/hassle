"""Golden case: repeat_while(cond) -> HA's `repeat.while` action."""

from hassle import automation, repeat_while, service, state, when


@automation(id="repeat_while_counter", alias="Repeat while counter")
def repeat_while_counter():
    when(state("sensor.counter").to("changed"))
    with repeat_while(state("input_boolean.counting").is_("on")):
        service("input_number.increment", target={"entity_id": "input_number.counter"})
