"""Error case: param() references a name absent from the shared script's
signature."""

from hassle import param, service, shared_script


@shared_script(id="flash_lights", alias="Flash lights")
def flash_lights(times: int = 3):
    service("light.turn_on", entity_id="light.all", brightness=param("brightness"))
