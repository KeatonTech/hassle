"""M3 done-gate fixture: a synthetic bundle referencing ONLY entities/helpers
that exist in `fixtures/registry/home.json` or are declared in this same
bundle. Validating this must produce zero Findings.
"""

from hassle import (
    area,
    automation,
    input_boolean,
    label,
    met,
    on,
    only_if,
    service,
    state,
    template,
    when,
)

VACATION_MODE = input_boolean(id="vacation_mode", name="Vacation Mode")


@automation(id="clean_hallway_motion", alias="Clean: hallway motion")
def clean_hallway_motion():
    when(state("binary_sensor.hall_motion").to("on"))
    only_if(state(VACATION_MODE).is_("off"))
    service("light.turn_on", target={"entity_id": "light.hallway"}, brightness_pct=80)


@automation(id="clean_purpose_trigger", alias="Clean: purpose trigger")
def clean_purpose_trigger():
    when(on("motion.detected", target=area("office"), behavior="first"))
    only_if(met("climate.is_target_temperature", target=label("work")))
    service("notify.mobile_app_keaton", message="Office motion detected")


@automation(id="clean_template_ref", alias="Clean: template reference")
def clean_template_ref():
    when(template("{{ states('sensor.outdoor_temperature') | float > 25 }}"))
    service(
        "notify.notify",
        target={"entity_id": "notify.phone"},
        message=template("{{ state_attr('light.hallway', 'brightness') }}"),
    )
