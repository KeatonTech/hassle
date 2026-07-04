"""Golden case: standalone @script objects (DESIGN §5.7).

Covers the three script_*.json corpus shapes:
- a basic script (bare sequence),
- a script with mode=queued + max,
- a script with a full `fields` mapping carrying name/description/example/
  default metadata (authored explicitly via fields=, since a plain @script's
  fields are not derived from a signature — that's @shared_script's job).
"""

from hassle import delay, script, service


@script(id="basic_greet", alias="Basic Greet")
def basic_greet():
    service("notify.mobile_app", message="hello")


@script(id="queued_worker", alias="Queued Worker", mode="queued", max=10)
def queued_worker():
    service("switch.turn_on", target={"entity_id": "switch.pump"})
    delay(seconds=5)
    service("switch.turn_off", target={"entity_id": "switch.pump"})


@script(
    id="script_with_fields",
    alias="Script With Fields",
    description="A script with input fields for parameters",
    fields={
        "light_entity": {
            "name": "Light Entity",
            "description": "The light to control",
            "example": "light.bedroom",
        },
        "brightness": {
            "name": "Brightness",
            "description": "Brightness level 0-255",
            "example": 200,
            "default": 255,
        },
    },
)
def script_with_fields():
    service(
        "light.turn_on",
        target={"entity_id": "{{ light_entity }}"},
        data={"brightness": "{{ brightness }}"},
    )
