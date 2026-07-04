"""Golden case: @shared_script compiles to a script object AND a call action
(M1 test 3, DESIGN §5.6).

`flash_lights` becomes a real HA script (fields derived from the signature,
defaults -> field defaults) whose sequence references `param("times")` and
`param("brightness")` as runtime template reads. The caller automation's
action list gets a `script.turn_on`-style call action (matching the corpus
script-call shape), never a re-run of the body.
"""

from hassle import automation, param, service, shared_script, state, when


@shared_script(id="flash_lights", alias="Flash lights", icon="mdi:alarm-light")
def flash_lights(times: int = 3, brightness: int = 255):
    service(
        "light.turn_on",
        entity_id="light.all_downstairs",
        brightness=param("brightness"),
    )
    service("light.turn_off", entity_id="light.all_downstairs")


@automation(id="guest_arrived", alias="Guest arrived")
def guest_arrived():
    when(state("binary_sensor.guest_sensor").to("on"))
    flash_lights(times=5, brightness=128)
