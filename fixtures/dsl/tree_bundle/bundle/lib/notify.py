"""lib/notify.py — shared macro library (DESIGN §5.6), one directory level
down from the bundle root. Exercises a package import from `automations/`."""

from hassle import macro, service


@macro
def notify_adults(message: str):
    service("notify.mobile_app_kai", message=message)
    service("notify.mobile_app_spouse", message=message)
