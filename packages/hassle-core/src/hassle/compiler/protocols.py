"""Extension-point protocols for builder families outside the compiler core.

The compiler core records triggers, conditions and actions into the active
automation via three small, stable extension points. Other builder families
(e.g. triggers/conditions, actions/control-flow) add themselves by
implementing these protocols — they never touch the recorder, the span machinery,
or the pipeline. See docs/internals/compiler-api.md.

Serialization contract: a builder emits a plain ``dict[str, Any]`` in HA's **plural
canonical schema** (§7.1) — ``{"trigger": "<type>", ...}`` for triggers,
``{"condition": "<type>", ...}`` for conditions, an action mapping (with ``action:``
never ``service:``) for actions. Emitting canonical (already-normalized) dicts keeps
the compiler output byte-stable (no wall clock or randomness in core logic).
``normalize_ha`` is applied to whole objects as a backstop, but builders should
emit canonical form directly.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class TriggerBuilder(Protocol):
    """Anything that can serialize itself as an HA trigger mapping.

    Registered into the active automation by ``when(...)``. ``to_trigger`` returns
    the canonical trigger dict (``{"trigger": "<type>", ...}``).
    """

    def to_trigger(self) -> dict[str, Any]: ...


@runtime_checkable
class ConditionBuilder(Protocol):
    """Anything that can serialize itself as an HA condition mapping.

    Registered into the active automation by ``only_if(...)``. ``to_condition``
    returns the canonical condition dict (``{"condition": "<type>", ...}``).
    """

    def to_condition(self) -> dict[str, Any]: ...


@runtime_checkable
class ActionBuilder(Protocol):
    """Anything that can serialize itself as an HA action mapping.

    Appended to the active action list at record time. ``to_action`` returns the
    canonical action dict (service call, ``delay``, ``choose``/``if``/``repeat``/…).
    """

    def to_action(self) -> dict[str, Any]: ...
