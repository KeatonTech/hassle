"""Golden case: repeat_count(n) -> HA's `repeat.count` action."""

from hassle import automation, delay, repeat_count, service, state, when


@automation(id="porch_repeat_count", alias="Porch repeat count")
def porch_repeat_count():
    when(state("button.test").to("pressed"))
    with repeat_count(3):
        service("light.toggle", target={"entity_id": "light.hallway"})
        delay(seconds=1)
