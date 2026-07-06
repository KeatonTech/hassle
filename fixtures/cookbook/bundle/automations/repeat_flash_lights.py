"""Cookbook recipe 18: repeat-flash the lights N times.

`repeat_count` around a toggle+delay pair -- the classic "get my attention"
pattern (e.g. announcing a doorbell visually).
"""

from hassle import automation, delay, repeat_count, service, state, when


@automation(id="cookbook_repeat_flash_lights", alias="Cookbook: repeat flash lights")
def cookbook_repeat_flash_lights():
    when(state("binary_sensor.front_door").to("open"))
    with repeat_count(3):
        service("light.toggle", target={"entity_id": "light.hallway"})
        delay(seconds=1)
