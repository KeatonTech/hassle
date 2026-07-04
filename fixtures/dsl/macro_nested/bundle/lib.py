"""Nested macros (M1 test 2): a macro calling another macro."""

from hassle import macro, service


@macro
def flash_porch():
    service("light.turn_on", entity_id="light.porch")
    service("light.turn_off", entity_id="light.porch")


@macro
def welcome_home(message: str):
    flash_porch()
    service("notify.mobile_app_keaton", message=message)
