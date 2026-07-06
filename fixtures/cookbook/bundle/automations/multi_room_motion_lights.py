"""Cookbook recipe 22: multi-room motion lights via a compile-time loop + macro.

Python `for` at module scope generates one automation per room (DESIGN §5.5
metaprogramming-for-free); each one reuses the `notify_household` macro from
`lib/notify.py` (DESIGN §5.6) so the notification wording can never drift
between rooms.
"""

from lib.notify import notify_household

from hassle import automation, only_if, service, state, when

ROOMS = ["kitchen", "office"]

for room in ROOMS:

    @automation(id=f"cookbook_motion_{room}", alias=f"Cookbook: motion light ({room})")
    def _cookbook_motion(room: str = room) -> None:
        when(state(f"binary_sensor.{room}_motion").to("on"))
        only_if(state("input_boolean.guest_mode").is_("off"))
        service("light.turn_on", entity_id=f"light.{room}")
        notify_household(f"Motion detected in the {room}")
