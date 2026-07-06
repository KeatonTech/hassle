"""Error case: an action recorded BEFORE a `with only_if(...):` block opens
(`ux/dsl-ergonomics`, item 1) -- the block form requires every action to be
inside it; one already recorded earlier can never retroactively become
"inside" the block.
"""

from hassle import automation, only_if, service, state


@automation(id="bad_only_if_before", alias="Bad only_if before")
def bad_only_if_before():
    service("light.turn_on", entity_id="light.a")
    with only_if(state("input_boolean.guest_mode").is_("off")):
        service("light.turn_off", entity_id="light.a")
