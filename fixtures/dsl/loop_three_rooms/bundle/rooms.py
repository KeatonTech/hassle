"""Golden case: a compile-time `for` loop generating three automations.

DESIGN §5.5: Python `for` runs at compile time. Looping over rooms to generate
one automation per room is metaprogramming for free — three distinct objects
land in the IR.
"""

from hassle import automation, only_if, service, state, when

ROOMS = ["kitchen", "office", "bedroom"]

for room in ROOMS:

    @automation(id=f"motion_{room}", alias=f"Motion light: {room}")
    def _motion(room: str = room):
        when(state(f"binary_sensor.{room}_motion").to("on"))
        only_if(state("input_boolean.guest_mode").is_("off"))
        service("light.turn_on", entity_id=f"light.{room}")
