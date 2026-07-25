"""Shared macro library: notify_adults (DESIGN §5.6)."""

from hassle import macro, service


@macro
def notify_adults(message: str):
    service("notify.mobile_app_kai", message=message)
    service("notify.mobile_app_spouse", message=message)
