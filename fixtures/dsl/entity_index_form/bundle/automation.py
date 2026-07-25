"""Golden case: entity indexing form, index access (DESIGN §5.2).

`e.sensor["hall_motion"]` must compile to the same entity_id as the attribute
form (fixtures/dsl/entity_attr_form).
"""

from hassle import automation, state, when
from hassle.registry import entities as e


@automation(id="entity_index_form", alias="Entity index form")
def entity_index_form():
    when(state(e.sensor["hall_motion"]).to("on"))
