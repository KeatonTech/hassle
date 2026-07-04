"""Golden case: repeat_while(cond) -> HA's `repeat.while` action.

The while condition is a `template(...)` condition — the corpus shape
UI-authored `repeat` loops carry (`condition: template`), so the golden mirrors
the real fixture shape rather than a placeholder state condition.
"""

from hassle import automation, repeat_while, service, state, template, when


@automation(id="repeat_while_counter", alias="Repeat while counter")
def repeat_while_counter():
    when(state("sensor.counter").to("changed"))
    with repeat_while(template("{{ states('input_number.counter') | int < 10 }}")):
        service("input_number.increment", target={"entity_id": "input_number.counter"})
