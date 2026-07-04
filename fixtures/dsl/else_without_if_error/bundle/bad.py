"""Error case: `with else_then():` with no preceding `if_then`/`choose` action."""

from hassle import automation, else_then, service


@automation(id="bad_else", alias="Bad else")
def bad_else():
    service("light.turn_on", entity_id="light.a")
    with else_then():
        service("light.turn_off", entity_id="light.a")
