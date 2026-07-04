"""Macro with args (M1 test 2): args are compile-time Python values."""

from hassle import macro, service


@macro
def flash_light(entity_id: str, *, times: int = 2):
    # `times` is a compile-time int: an ordinary Python loop, unrolled at
    # compile time into `times` pairs of actions (DESIGN §5.5: Python `for`
    # runs at compile time).
    for _ in range(times):
        service(f"{entity_id.split('.')[0]}.turn_on", entity_id=entity_id)
        service(f"{entity_id.split('.')[0]}.turn_off", entity_id=entity_id)
