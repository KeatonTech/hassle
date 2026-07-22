"""Cookbook recipe 7: door-left-open reminder.

`for_=` on a state trigger: only fires once the door has held "open" for
10 minutes straight (resets on any flap back to "closed").
"""

from hassle import automation, minutes, service, state, when


@automation(id="cookbook_door_left_open", alias="Cookbook: door left open")
def cookbook_door_left_open():
    when(state("binary_sensor.laundry_door").to("open", for_=minutes(10)))
    service("notify.mobile_app_kai", message="Laundry door has been open for 10 minutes")
