"""Error case: a macro called outside any recording context (module scope)."""

from hassle import macro, service


@macro
def notify_all(message: str):
    service("notify.mobile_app_keaton", message=message)


# Called at module scope -- no @automation/@script recording context is active.
notify_all("oops")
