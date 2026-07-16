"""Golden case: an automation calling a macro that itself calls a macro."""

from lib import welcome_home

from hassle import automation, state, when


@automation(id="arrival", alias="Arrival")
def arrival():
    when(state("person.kai").to("home"))
    welcome_home("Welcome home")
