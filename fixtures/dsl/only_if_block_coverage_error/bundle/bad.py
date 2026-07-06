"""Error case: an action recorded AFTER a `with only_if(...):` block closes
(`ux/dsl-ergonomics`, item 1) -- automation-level conditions gate every
action, so once the block form is used, every action must be inside it.
"""

from hassle import automation, only_if, service, state


@automation(id="bad_only_if", alias="Bad only_if")
def bad_only_if():
    with only_if(state("input_boolean.guest_mode").is_("off")):
        service("light.turn_on", entity_id="light.a")
    service("light.turn_off", entity_id="light.a")
