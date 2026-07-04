"""Golden case: blueprint_automation (DESIGN §5.8 / ha-api-notes §10.5).

The ergonomic DSL ``inputs=`` maps to the stored ``use_blueprint.input``
(singular) with an author-qualified blueprint path. A blueprint automation
carries only ``use_blueprint`` — no triggers/conditions/actions.
"""

from hassle import blueprint_automation

blueprint_automation(
    id="hall_motion_blueprint",
    use_blueprint="hassle/motion_light.yaml",
    inputs={
        "motion_entity": "binary_sensor.hall_motion",
        "light_target": "light.hallway",
        "no_motion_wait": 90,
    },
)
