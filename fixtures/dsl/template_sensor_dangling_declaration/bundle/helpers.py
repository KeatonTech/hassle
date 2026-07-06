"""Error case (M13 reviewer finding B1): `template_sensor` called with no
`state=` (the decorator-form signal) but never applied as a decorator over a
function. On the pre-M13 call form this line registered a degenerate
(`state=None`) object; after M13 added decorator detection, a bare call like
this now does nothing at all -- silently, unless caught. Must fail at compile
time (`DanglingTemplateHelperDeclarationError`), not compile clean with the
object simply absent (I6: a helper that already exists in HA would otherwise
vanish from the compiled set and get scheduled for DELETE on the next
plan/push)."""

from hassle import template_sensor

template_sensor(name="Ghost Sensor")
