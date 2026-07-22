"""The granular ``raw_*`` escape hatch (DESIGN §5.8; compile(decompile(x))
must equal x for any config), scoped to what this module's extension points
can reach.

``raw_trigger({...})`` / ``raw_condition({...})`` / ``raw_action({...})`` pass
a verbatim dict through into the recorded stream of the *currently active*
automation/script, exactly like any other trigger/condition/action builder
(docs/internals/compiler-api.md §1/§2: "any object with ``to_trigger()``"). The
containing object's whole-body ``normalize_ha`` pass (already applied by
``compile_registered``/``_build_automation`` in the core) normalizes them
exactly as HA itself would on storage -- e.g. a raw action given in legacy
``service:`` form comes out as ``action:`` -- with no extra work here; a raw
trigger's inner ``platform:`` discriminator is preserved verbatim (HA does not
rewrite it on storage, docs/internals/ha-api-notes.md §10.1), which these passthrough
builders get for free by not touching the dict at all.

**Scope note:** ``@raw_automation`` (a whole raw automation as a bundle-level
object) and ``@blueprint_automation`` are *not* in this module -- they are
whole top-level objects (a different registration shape than "run a function,
record trigger/condition/action calls into it") and live in
``hassle.compiler.raw_automation`` instead, alongside the ``Registry.
add_object`` path (registry.py) that lands them in ``CompileResult.objects``.
This was originally a reported contract gap (docs/internals/ha-api-notes.md §12);
see that module's docstring.
"""

from __future__ import annotations

from typing import Any

from hassle.compiler.recording import record_action, record_condition, record_trigger
from hassle.compiler.spans import capture_span


class RawTrigger:
    """A verbatim trigger dict, passed through unmodified (DESIGN §5.8)."""

    def __init__(self, body: dict[str, Any]) -> None:
        self._body = dict(body)

    def to_trigger(self) -> dict[str, Any]:
        return dict(self._body)


class RawCondition:
    """A verbatim condition dict, passed through unmodified (DESIGN §5.8)."""

    def __init__(self, body: dict[str, Any]) -> None:
        self._body = dict(body)

    def to_condition(self) -> dict[str, Any]:
        return dict(self._body)


class RawAction:
    """A verbatim action dict, passed through unmodified (DESIGN §5.8).

    Legacy ``service:`` form is normalized to ``action:`` by the containing
    object's whole-body ``normalize_ha`` pass (already applied by the core
    compiler) -- this builder does not need to normalize anything itself.
    """

    def __init__(self, body: dict[str, Any]) -> None:
        self._body = dict(body)

    def to_action(self) -> dict[str, Any]:
        return dict(self._body)


def raw_trigger(body: dict[str, Any]) -> None:
    """Record a verbatim trigger dict on the active automation (DESIGN §5.8)."""
    record_trigger(RawTrigger(body), span=capture_span(depth=0))


def raw_condition(body: dict[str, Any]) -> None:
    """Record a verbatim condition dict on the active automation (DESIGN §5.8)."""
    record_condition(RawCondition(body), span=capture_span(depth=0))


def raw_action(body: dict[str, Any]) -> None:
    """Record a verbatim action dict on the active automation/script (DESIGN §5.8)."""
    record_action(RawAction(body), span=capture_span(depth=0))
