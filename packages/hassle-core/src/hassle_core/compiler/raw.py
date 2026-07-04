"""The granular ``raw_*`` escape hatch (DESIGN §5.8, I3), scoped to what this
workstream's extension points can reach.

``raw_trigger({...})`` / ``raw_condition({...})`` / ``raw_action({...})`` pass
a verbatim dict through into the recorded stream of the *currently active*
automation/script, exactly like any other trigger/condition/action builder
(docs/m1-internal-api.md §1/§2: "any object with ``to_trigger()``"). The
containing object's whole-body ``normalize_ha`` pass (already applied by
``compile_registered``/``_build_automation`` in the core) normalizes them
exactly as HA itself would on storage -- e.g. a raw action given in legacy
``service:`` form comes out as ``action:`` -- with no extra work here; a raw
trigger's inner ``platform:`` discriminator is preserved verbatim (HA does not
rewrite it on storage, docs/ha-api-notes.md §10.1), which these passthrough
builders get for free by not touching the dict at all.

**Scope note (contract gap, reported to the orchestrator/human):**
``@raw_automation`` (a whole raw automation as a bundle-level object) and
``@blueprint_automation`` need a *new top-level object kind* to enter
``CompileResult.objects`` -- something other than "run a function, record
trigger/condition/action calls into it". That requires either a new
``Registry``/``RegisteredObject`` registration path (registry.py) or a new
branch in ``compile_registered`` (bundle.py) that skips the recorder and
calls ``CompileResult.add()`` directly with a pre-built IR object. Both files
are off-limits to this workstream (docs/m1-internal-api.md marks ``bundle.py``
"No", and ``registry.py`` -- while not listed in that table at all -- has no
seam for a non-function registration today). Per the instruction to "stop and
report rather than modifying core" when the internal-api contract is
insufficient, ``raw_automation``/``@blueprint_automation`` are NOT implemented
here; see docs/ha-api-notes.md for the recorded finding and the final report
for the exact minimal change needed.
"""

from __future__ import annotations

from typing import Any

from hassle_core.compiler.recording import record_action, record_condition, record_trigger
from hassle_core.compiler.spans import capture_span


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
