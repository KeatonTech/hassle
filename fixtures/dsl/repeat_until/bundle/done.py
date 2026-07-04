"""Golden case: repeat_until(cond) -> HA's `repeat.until` action.

The until condition is a `template(...)` condition — the corpus shape
UI-authored `repeat` loops carry (`condition: template`), so the golden mirrors
the real fixture shape rather than a placeholder state condition.
"""

from hassle import automation, repeat_until, service, state, template, when


@automation(id="repeat_until_done", alias="Repeat until done")
def repeat_until_done():
    when(state("input_boolean.done").to("off"))
    with repeat_until(template("{{ is_state('input_boolean.done', 'on') }}")):
        service("input_boolean.turn_on", target={"entity_id": "input_boolean.done"})
