"""Golden case: blueprint_local_expansion (DESIGN §5.8 / §10.1).

A `blueprint_automation` whose blueprint is a BUNDLE-LOCAL file at
``blueprints/automation/<use_blueprint path>`` (this bundle carries
``blueprints/automation/local/room-switch-controls.yaml``, mirroring HA's own
``config/blueprints/automation/`` layout).

The compiled IR is unchanged by that file's existence -- an instance still
stores only ``use_blueprint`` -- which is exactly what this golden pins. The
expansion the simulator performs on top of it is asserted separately, in
``test_blueprint_expansion.py``.
"""

from hassle import blueprint_automation

blueprint_automation(
    id="office_switch_controls",
    alias="Office switch controls",
    use_blueprint="local/room-switch-controls.yaml",
    inputs={
        "switch_entity": "sensor.office_paddle",
        "room_light": "light.office",
    },
)
