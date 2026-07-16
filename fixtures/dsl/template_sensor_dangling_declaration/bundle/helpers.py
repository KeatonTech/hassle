"""Error case: `template_sensor` called with no `state=` (the
decorator-form signal) but never applied as a decorator over
a function. A bare call like this must not silently register
a degenerate (`state=None`) object, and it must not silently
do nothing at all either -- it must fail at compile time
(`DanglingTemplateHelperDeclarationError`), not compile clean
with the object simply absent (I6: a helper that already
exists in HA would otherwise vanish from the compiled set and
get scheduled for DELETE on the next plan/push)."""

from hassle import template_sensor

template_sensor(name="Ghost Sensor")
