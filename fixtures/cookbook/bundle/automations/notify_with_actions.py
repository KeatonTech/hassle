"""Cookbook recipe 4: notify with a title.

A `notify.notify` call with both `message` and `title` set (the fields
`get_services` actually reports for this instance, per the registry
snapshot -- see the M9 validator coverage-boundaries note in docs/DSL.md for
why a service param check is strict whenever the schema is non-empty) when
the front door unlocks unexpectedly.
"""

from hassle import automation, service, state, when


@automation(id="cookbook_notify_with_actions", alias="Cookbook: door unlocked notify")
def cookbook_notify_with_actions():
    when(state("lock.front_door").to("unlocked"))
    service(
        "notify.notify",
        message="Front door unlocked",
        title="Security",
    )
