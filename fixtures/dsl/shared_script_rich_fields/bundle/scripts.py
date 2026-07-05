"""Golden case: `@shared_script(fields=...)` carries full HA field metadata
(`ux/shared-script-rich-fields`, owner feedback: real HA-UI-authored scripts
carry `selector`/`name`/`description` on every field, mirroring
`call_to_action_notification`'s shape -- title/message/action_button/
action_button_icon/tag text selectors).

`fields=` wins over the signature-derived defaults (byte-stability by
construction): the stored `ScriptConfig.fields` is exactly this dict,
verbatim. The signature stays the ergonomic call-site layer -- every field
name is still a real Python parameter, `None`-defaulted, so the call site
(`notify_all(title=..., message=...)`) and `param()` inside the body both
still work.
"""

from hassle import automation, param, service, shared_script, state, when


@shared_script(
    id="notify_all",
    alias="Notify all",
    fields={
        "title": {
            "name": "Title",
            "description": "Notification title",
            "selector": {"text": {}},
        },
        "message": {
            "name": "Message",
            "description": "Notification message",
            "selector": {"text": {}},
        },
        "action_button": {
            "name": "Action button",
            "description": "Label for the notification's action button",
            "selector": {"text": {}},
        },
        "action_button_icon": {
            "name": "Action button icon",
            "description": "mdi icon for the action button",
            "selector": {"text": {}},
        },
        "tag": {
            "name": "Tag",
            "description": "Notification tag (dedupes repeat notifications)",
            "selector": {"text": {}},
        },
    },
)
def notify_all(title=None, message=None, action_button=None, action_button_icon=None, tag=None):
    service(
        "notify.mobile_app_keaton",
        title=param("title"),
        message=param("message"),
        data={
            "actions": [
                {
                    "action": "VIEW",
                    "title": param("action_button"),
                    "icon": param("action_button_icon"),
                }
            ],
            "tag": param("tag"),
        },
    )


@automation(id="garage_door_opened", alias="Garage door opened")
def garage_door_opened():
    when(state("cover.garage_door").to("open"))
    notify_all(
        title="Garage",
        message="Door opened",
        action_button="view",
        action_button_icon="mdi:garage-open",
        tag="garage_door",
        metadata={},
    )
