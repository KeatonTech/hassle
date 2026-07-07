"""Golden case: `hassle.services` namespace calls, entity-method sugar, and
plain `service()` calls all compile to byte-identical IR (MILESTONES M18
test 2).

Multi-domain (light + switch) to exercise the module `__getattr__` accepting
more than one domain in the same file.
"""

from hassle import automation
from hassle.registry import entities as e
from hassle.services import light, switch


@automation(id="namespace_sugar_demo", alias="Namespace sugar demo")
def namespace_sugar_demo():
    # Namespace form.
    light.turn_on(target={"entity_id": "light.hallway"}, brightness_pct=60)
    # Entity-method form -- implicit target.
    e.switch.porch.turn_on()
    switch.turn_off(target={"entity_id": "switch.porch"})
