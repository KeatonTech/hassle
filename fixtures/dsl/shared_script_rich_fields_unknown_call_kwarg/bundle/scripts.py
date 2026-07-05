"""Error case: `fields=` is the superset source of truth for call-site kwarg
validation, not just the Python signature (`ux/shared-script-rich-fields`).

``notify_all`` declares a real Python parameter ``untracked`` that is NOT one
of ``fields=``'s keys (an authoring mistake: added a parameter but forgot to
also declare it as a field) -- calling with ``untracked=...`` must be
rejected even though it would otherwise bind fine against the signature.
"""

from hassle import automation, service, shared_script, state, when


@shared_script(
    id="notify_all",
    fields={
        "title": {"name": "Title", "selector": {"text": {}}},
    },
)
def notify_all(title=None, untracked=None):
    service("notify.mobile_app_keaton", title=title)


@automation(id="garage_door_opened", alias="Garage door opened")
def garage_door_opened():
    when(state("cover.garage_door").to("open"))
    notify_all(title="Garage", untracked="oops")
