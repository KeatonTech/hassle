"""Golden case (M19, owner-directed typing resolution): `field_default(...)`
is the typed-default helper for a `@shared_script` signature parameter
annotated `TemplateExpr` -- the BODY-TRUE type (every field-named parameter
is a runtime template marker inside the body, never its declared Python
default's type). `field_default(value)` is the identity function AT RUNTIME
(the compiler's `inspect.signature(...)` introspection sees the real
declared default, e.g. the plain `str` `""` below, completely unchanged) but
is TYPED as returning `TemplateExpr`, so the parameter's own default
expression type-checks against its `TemplateExpr` annotation without the
self-inconsistent `tag: TemplateExpr = ""` a bare literal default would be.

Caller-side typing is unaffected either way (verified empirically,
MILESTONES M19 typing investigation): a caller passing a plain literal
(`dismiss_tagged_notification(tag="guest_reminder")`) is unaffected by
whatever this signature's own annotations say -- `@shared_script`'s returned
caller wrapper is `(*args: Any, **kwargs: Any) -> None`, fully decoupled.
"""

from hassle import automation, field_default, service, shared_script, state, when
from hassle.compiler.templates import TemplateExpr


@shared_script(id="dismiss_tagged_notification_typed", alias="Dismiss tagged (typed)")
def dismiss_tagged_notification_typed(tag: TemplateExpr = field_default("")):
    # Body-true composition: `tag` is a TemplateExpr marker, so `.eq(...)`
    # type-checks correctly (a `str`-annotated `tag` would NOT: `str` has no
    # `.eq()` method, `reportAttributeAccessIssue`).
    service(
        "persistent_notification.dismiss",
        notification_id=tag,
    )


@automation(id="dismiss_tagged_reminder_typed", alias="Dismiss tagged reminder (typed)")
def dismiss_tagged_reminder_typed():
    when(state("input_boolean.guest_mode").to("off"))
    dismiss_tagged_notification_typed(tag="guest_reminder")
