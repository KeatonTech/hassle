"""Cookbook recipe 9: daily vacuum run.

A `time` trigger starting the downstairs vacuum every morning while everyone
is out (a second `only_if` gate).
"""

from hassle import automation, only_if, service, state, time, when


@automation(id="cookbook_vacuum_daily", alias="Cookbook: daily vacuum")
def cookbook_vacuum_daily():
    when(time(at="10:00:00"))
    only_if(state("input_boolean.armed").is_("on"))
    service("vacuum.start", target={"entity_id": "vacuum.downstairs"})
