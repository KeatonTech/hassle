"""Golden case: entity indexing form, attribute access (M1 test 8, DESIGN §5.2).

`e.sensor.hall_motion` must compile to the same entity_id as the index form
(fixtures/dsl/entity_index_form).
"""

from hassle import automation, state, when
from hassle.registry import entities as e


@automation(id="entity_attr_form", alias="Entity attr form")
def entity_attr_form():
    when(state(e.sensor.hall_motion).to("on"))
