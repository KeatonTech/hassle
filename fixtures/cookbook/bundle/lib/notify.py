"""Cookbook shared macro library (DESIGN §5.6): notify both housemates."""

from hassle import macro, service


@macro
def notify_household(message: str) -> None:
    service("notify.mobile_app_keaton", message=message)
    service("notify.mobile_app_spouse", message=message)
