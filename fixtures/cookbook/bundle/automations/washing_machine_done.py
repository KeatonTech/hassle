"""Cookbook recipe 5: washing-machine-done.

`numeric_state` crossing DOWN through a low-power threshold (the machine
finished its cycle and drew almost no power) -- the "only fires on the
cross, not while already below" behavior DESIGN §10.1 calls out.
"""

from hassle import automation, numeric_state, service, when


@automation(id="cookbook_washing_machine_done", alias="Cookbook: washing machine done")
def cookbook_washing_machine_done():
    when(numeric_state("sensor.washing_machine_power", below=3))
    service("notify.mobile_app_kai", message="Washing machine finished")
