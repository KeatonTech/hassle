"""Error case (M19 test 2): `if tag:` on a bound shared-script parameter.

Since M19, `tag` inside the body IS the runtime `param("tag")` marker (bound
from the signature regardless of its declared default), so a native Python
`if` on it is a `CompileTimeBranchError` -- specialized here to also name the
`param_default()` escape hatch, since the underlying trap
(`TemplateExpr.__bool__`) doesn't know about shared-script params.
"""

from hassle import service, shared_script


@shared_script(id="dismiss_notification_if_misuse", alias="Dismiss (if misuse)")
def dismiss_notification_if_misuse(tag: str = ""):
    if tag:
        service("persistent_notification.dismiss", notification_id=tag)
