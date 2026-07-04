"""Golden case: if_then / else_if / else_then chain -> HA's `choose` action.

Multiple mutually-exclusive branches (`if` + one or more `else_if`) compile to
a `choose` action (HA has no native `elif`); the trailing `else_then` becomes
the `choose`'s `default`.
"""

from hassle import automation, else_if, else_then, if_then, service, state, when


@automation(id="climate_elseif", alias="Climate if/elif/else")
def climate_elseif():
    when(state("sensor.temperature").to("changed"))
    target = {"entity_id": "climate.living_room"}
    with if_then(state("sensor.temperature").is_("hot")):
        service("climate.set_temperature", target=target, temperature=18)
    with else_if(state("sensor.temperature").is_("cold")):
        service("climate.set_temperature", target=target, temperature=24)
    with else_then():
        service("climate.set_temperature", target=target, temperature=21)
