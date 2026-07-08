"""Error case (M19): `param_default(name)` naming a field with NO declared
default at all -- there is no compile-time value to hand back, a distinct
mistake from an unknown-name typo (`NoDeclaredDefaultError`, not
`UnknownParamError`).

`tag` has no `=...` in the signature at all, so its field spec is `{}` (no
`"default"` key) -- `param_default("tag")` can never return anything
meaningful for it, even though `tag` itself is a perfectly valid field
(`param("tag")` works fine; only `param_default` is the problem here).
"""

from hassle import service, shared_script
from hassle.compiler.scripts import param_default


@shared_script(id="dismiss_no_default", alias="Dismiss (no default)")
def dismiss_no_default(tag):
    service(
        "persistent_notification.dismiss",
        notification_id=param_default("tag"),
    )
