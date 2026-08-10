"""Golden case: blueprint_managed_object (blueprints-design §1/§7).

The blueprint FILE is a managed object here, not just something the simulator
reads: this bundle compiles to THREE objects -- two `blueprint_automation`
instances and the `blueprint:automation/local/room-switch-controls.yaml`
source file itself, discovered from `blueprints/automation/` by
`compile_bundle`.

Two instances, not one, on purpose: §4's ordering rules are about a blueprint
and its instances as a group (every instance saved after the file exists,
every instance deleted before it goes), and one instance cannot tell a
correct implementation from one that happens to order a single pair right.
`test_blueprint_golden_bundle.py` drives this bundle end to end through
plan -> apply -> delete against FakeBackend and pins the whole sequence.
"""

from hassle import blueprint_automation

SWITCHES = {
    "office": ("sensor.office_paddle", "light.office"),
    "hallway": ("sensor.hallway_paddle", "light.hallway"),
}

for _room, (_paddle, _light) in SWITCHES.items():
    blueprint_automation(
        id=f"{_room}_switch_controls",
        alias=f"{_room.title()} switch controls",
        use_blueprint="local/room-switch-controls.yaml",
        inputs={"switch_entity": _paddle, "room_light": _light},
    )
