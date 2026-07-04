"""Golden case: wait_template(tmpl, timeout=) -> HA's `wait_template` action."""

from hassle import automation, service, state, wait_template, when


@automation(id="wait_template_hallway", alias="Wait template")
def wait_template_hallway():
    when(state("binary_sensor.motion").to("on"))
    wait_template(
        "{{ state_attr('light.hallway', 'brightness') > 100 }}",
        timeout="00:05:00",
    )
    service("light.turn_off", target={"entity_id": "light.hallway"})
