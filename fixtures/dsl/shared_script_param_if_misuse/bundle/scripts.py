"""Error case (M19 test 2): `if tag:` on a bound shared-script parameter.

Since M19, `tag` inside the body IS the runtime `param("tag")` marker (bound
from the signature regardless of its declared default), so a native Python
`if` on it raises `SharedScriptParamMisuseError` (specialized over the
generic `CompileTimeBranchError`/`TemplateExpr.__bool__` trap) teaching the
honest alternatives -- a runtime construct HA itself supports, or a
module constant / `@macro` argument for a genuinely compile-time value.
No `param_default()` escape hatch (owner amendment: rejected as an
anti-pattern that bakes a stale compile-time value into the compiled
sequence while the field still exists).
"""

from hassle import service, shared_script


@shared_script(id="dismiss_notification_if_misuse", alias="Dismiss (if misuse)")
def dismiss_notification_if_misuse(tag: str = ""):
    if tag:
        service("persistent_notification.dismiss", notification_id=tag)
