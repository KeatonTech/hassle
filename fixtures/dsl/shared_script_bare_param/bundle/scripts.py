"""Golden case: a shared-script's own signature parameters ARE
real runtime field references -- `tag=tag` instead of `tag=param("tag")` --
composable with the whole expression surface (`concat(tag, "_x")`).

`dismiss_tagged_notification`'s body mirrors a real-world
`dismiss_notification` shape (`fixtures/dsl/shared_script_call_metadata/`)
but with the field named `tag`, and a second field consumed through
`concat(...)` to prove composability with the rest of the template-builder
operator surface, not just a bare read.

Compiling this body must produce BYTE-IDENTICAL IR to the equivalent
`param("tag")` spelling (see `shared_script_call_metadata`'s
`notification_id=param("notification_id")` for that alternate form of the
same shape) -- proven directly in
`packages/hassle-core/tests/test_shared_script_real_params.py`, and pinned
here as a golden so any regression in the binding machinery shows up as
golden drift too.
"""

from hassle import automation, service, shared_script, state, when
from hassle.compiler.math_expr import concat


@shared_script(id="dismiss_tagged_notification", alias="Dismiss tagged notification")
def dismiss_tagged_notification(tag: str = "", suffix: str = ""):
    service(
        "persistent_notification.dismiss",
        notification_id=tag,
    )
    service(
        "persistent_notification.dismiss",
        notification_id=concat(tag, "_x"),
    )


@automation(id="dismiss_tagged_reminder", alias="Dismiss tagged reminder")
def dismiss_tagged_reminder():
    when(state("input_boolean.guest_mode").to("off"))
    dismiss_tagged_notification(tag="guest_reminder")
