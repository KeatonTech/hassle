"""Golden case: a `@shared_script` call carrying `metadata`/`alias`/`enabled`
step options (`ux/shared-script-calls`, owner feedback -- mirrors a real
"dismiss notification" UI-authored automation calling a managed script).

The caller passes `metadata={}` (the empty dict every UI-saved action carries,
docs/ha-api-notes.md §19.1) plus a step `alias`/`enabled`, which the
`ScriptCallAction` extension must reproduce verbatim on the recorded action.
"""

from hassle import automation, param, service, shared_script, state, when


@shared_script(id="dismiss_notification", alias="Dismiss notification")
def dismiss_notification(notification_id: str = ""):
    service(
        "persistent_notification.dismiss",
        notification_id=param("notification_id"),
    )


@automation(id="dismiss_reminder", alias="Dismiss reminder")
def dismiss_reminder():
    when(state("input_boolean.guest_mode").to("off"))
    dismiss_notification(
        notification_id="guest_reminder",
        metadata={},
        alias="Dismiss the guest reminder",
        enabled=False,
    )
