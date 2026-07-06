"""Cookbook recipe 8: good-morning scene via a `@shared_script`.

`good_morning` becomes a real HA script entity (visible/runnable/editable in
the HA UI); the automation's action list gets a `script.<id>`-style call, not
a re-run of the body (DESIGN §5.6).
"""

from hassle import automation, param, service, shared_script, state, when


@shared_script(id="cookbook_good_morning", alias="Good morning", icon="mdi:weather-sunny")
def cookbook_good_morning(brightness: int = 200):
    service("light.turn_on", entity_id="light.bedroom", brightness=param("brightness"))
    service("light.turn_on", entity_id="light.kitchen", brightness=param("brightness"))


@automation(id="cookbook_good_morning_trigger", alias="Cookbook: good morning trigger")
def cookbook_good_morning_trigger():
    when(state("input_boolean.armed").to("off"))
    cookbook_good_morning(brightness=180)
